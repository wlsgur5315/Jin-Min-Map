#!/usr/bin/env python3
"""Compare official NGII DEM GeoTIFF with the current Terrarium DEM (validation only).
Usage: python tools/compare_dem.py /path/to/ngii_5m.tif --count 150 --out dem_report
Install: pip install rasterio numpy requests pillow
The reference raster is sampled in its own CRS; location converted to WGS84 for Terrarium.
This program does not change map tiles, nor certify absolute elevation accuracy.
"""
import argparse, csv, io, json, math, statistics, time
from pathlib import Path
import numpy as np
import rasterio
from rasterio.warp import transform as reproject
import requests
from PIL import Image

URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

def terrarium(lon, lat, z, session, cache):
    if not (-85.0511 < lat < 85.0511):
        return None
    n = 2 ** z
    tx = ((lon + 180) / 360) * n
    ty = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    xi, yi = int(math.floor(tx)), int(math.floor(ty))
    if not (0 <= xi < n and 0 <= yi < n):
        return None
    key = (xi, yi)
    if key not in cache:
        res = session.get(URL.format(z=z, x=xi, y=yi), timeout=20)
        res.raise_for_status()
        cache[key] = np.asarray(Image.open(io.BytesIO(res.content)).convert("RGB"), dtype=np.float64)
    pixels = cache[key]
    # Native sample, nearest texel. Overzoomed z15 tiles do not create new terrain detail.
    px = min(255, max(0, int((tx - xi) * 256)))
    py = min(255, max(0, int((ty - yi) * 256)))
    red, green, blue = pixels[py, px]
    return red * 256 + green + blue / 256 - 32768

def main():
    p = argparse.ArgumentParser()
    p.add_argument("reference", help="Official 5m DEM as GeoTIFF, with known correct CRS")
    p.add_argument("--count", type=int, default=150)
    p.add_argument("--zoom", type=int, default=12, help="Native Terrarium zoom to inspect; use 10-15")
    p.add_argument("--out", default="dem_report")
    args = p.parse_args()
    if args.count < 2 or not (10 <= args.zoom <= 15):
        p.error("count >= 2 and zoom 10..15 required")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    random = np.random.default_rng(20261014)
    rows = []
    with rasterio.open(args.reference) as src:
        if src.crs is None:
            raise SystemExit("No source CRS: assign verified EPSG before comparison")
        data = src.read(1, masked=True)
        valid = np.flatnonzero(~np.ma.getmaskarray(data) & np.isfinite(np.asarray(data)))
        if not len(valid):
            raise SystemExit("No valid cells in reference DEM")
        choices = random.choice(valid, min(args.count, len(valid)), replace=False)
        with requests.Session() as session:
            cache = {}
            for idx in choices:
                row, col = np.unravel_index(int(idx), data.shape)
                x,y = src.xy(row,col)
                lon, lat = reproject(src.crs, "EPSG:4326", [x],[y])
                try:
                    current = terrarium(lon[0],lat[0],args.zoom,session,cache)
                except (requests.RequestException, ValueError, OSError) as err:
                    print("tile lookup failed",type(err).__name__)
                    continue
                ref = float(data[row,col])
                if current is None or not math.isfinite(ref):continue
                rows.append({"longitude":round(lon[0],7),"latitude":round(lat[0],7),
                             "ngii_m":round(ref,3),"terrarium_m":round(current,3),
                             "difference_m":round(current-ref,3)})
    if not rows:
        raise SystemExit("No overlapping samples; check coordinates, terrain tile access and raster validity.")
    error=np.array([r["difference_m"] for r in rows],dtype=float)
    report={"reference_file":Path(args.reference).name,"terrarium_zoom":args.zoom,
            "sample_count":len(rows),"bias_m":round(float(np.mean(error)),3),
            "mae_m":round(float(np.mean(np.abs(error))),3),
            "rmse_m":round(float(np.sqrt(np.mean(error**2))),3),
            "p95_absolute_m":round(float(np.percentile(np.abs(error),95)),3),
            "maximum_absolute_m":round(float(np.max(np.abs(error))),3),
            "cautions":["Difference from official raster, not a surveyed accuracy certification.",
                        "Vertical datum, source epochs and DEM vs DSM must be checked.",
                        "Terrarium tiles may have blended sources and different source resolution.",
                        "Do not infer better physical resolution by increasing tile zoom."]}
    with (out/"points.csv").open("w",newline="",encoding="utf-8-sig") as fh:
        writer=csv.DictWriter(fh,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
