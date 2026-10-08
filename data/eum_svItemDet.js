$(document).ready(function(){
	$("#dataType").on("change",function(){
		$("#detailForm input[name='subCurrentPageNo']").val(1);
		$("#detailForm input[name='dataTypeCd']").val($(this).val());
		$("#detailForm").submit();
	});
	
	$("#startDate, #endDate").on("change",function(){
		$.fn.search();
	});
	
});

$.fn.goItemList = function(){
	$("#listForm").submit();
}

$.fn.onSearch = function(pagaNum){
	$("#detailForm input[name='subCurrentPageNo']").val(pagaNum);
	$("#detailForm").submit();
}

$.fn.changeType = function(type){
	$("#detailForm input[name='subCurrentPageNo']").val(1);
	$("#detailForm input[name='dataTypeCd']").val(type.toUpperCase());
	$("#detailForm").submit();
}

$.fn.dataDownload = function(fileId){
	$("#useType").val("");
	$("#useDesc").val("");
	$("#fileList").val(fileId);
	$.fn.selectFileInfo();
	
}

$.fn.dataChkDownload = function(){
	$("#useType").val("");
	$("#useDesc").val("");
	
	var chkSize=$("#fileTb tbody td input[type='checkbox']:checked").length;
	if(chkSize<1){
		alert("선택된 자료가 존재하지 않습니다.");
		return;
	}
	
	var fileId="";
	$("#fileTb tbody td input[type='checkbox']:checked").each(function(index){
		if(index!=0){
			fileId+="@";
		}
		fileId+=$(this).val();;
	});
	$("#fileList").val(fileId);
	$.fn.selectFileInfo();
}

$.fn.closeLayer = function(){
	$("#useType").val("");
	$("#useDesc").val("");
	$("#fileList").val("");
	closeLayer('download_layer');
}


$.fn.selectFileInfo = function(){
	$.ajax({
		type:"POST", 
		url: context+"/op/sv/svItemAjaxXml.jsp",
		dataType:"json",  
		data:{
			"function" : "selectFileInfo",
			"dataCd" : $("#detailForm input[name='dataCd']").val(),
			"dataTypeCd" : $("#detailForm input[name='dataTypeCd']").val(),
			"refDt" : $("#useRefDt").val(),
			"fileId" : $("#fileList").val()
		},
		error:function(){   
			//console.log("예상치 못한 에러가 발생하였습니다.");   
		}, 
		success : function(data){
			var fileList = $.xml2json(data.fileList, true);
			$.fn.dextDown(fileList.node);
		},
		complete : function(){
		}
	});
}


var fileData=null;

$.fn.insertStatData = function(){
	
	var useType=$("#useType").val();
	var useDesc=$("#useDesc").val();
	if(useType==null || useType==''){
		alert("구분정보는 필수 입니다.");
		return ;
	}
	
	$.ajax({
		type:"POST", 
		url: context+"/op/sv/svItemAjaxXml.jsp",
		dataType:"json",  
		data:{
			"function" : "insertStatInfo",
			"dataCd" : $("#detailForm input[name='dataCd']").val(),
			"dataTypeCd" : $("#detailForm input[name='dataTypeCd']").val(),
			"useType" : useType,
			"useDesc" : useDesc
		},
		error:function(){   
			//console.log("예상치 못한 에러가 발생하였습니다.");   
		}, 
		success : function(data){
			$.cookie("statFlag",'true');
			$.cookie("useType",$("#useType").val());
			$.cookie("useDesc",$("#useDesc").val());
			location.href=updownUrl + "/OpenData/opDownloader.jsp?key="+fileData.key[0].text+"&filename="+fileData.fileNm[0].text;
			fileData=null;
			$.fn.closeLayer();
			//var dx = dx5.get("dext5");
			//dx5.get("dext5").download("AUTO", true);
		},
		complete : function(){
		}
	});
}

$.fn.dextDown = function(dataList){

	for(var i=0 ; i<dataList.length ; i++){
		if(i==0){
			fileData=dataList[i];
		}
		
	}	
	
	var statFlag=$.cookie("statFlag");
	if(statFlag=='true'){
		$("#statArea").hide();
		
		//쿠키정보 이용하여 매번 로그 남기도록 수정 - modified by tsjang (2024.03.13)
		//location.href=updownUrl + "/OpenData/opDownloader.jsp?key="+fileData.key[0].text+"&filename="+fileData.fileNm[0].text;
		//fileData=null;
		console.log("statFlag="+$.cookie("statFlag"));
		console.log("useType="+$.cookie("useType"));
		console.log("useDesc="+$.cookie("useDesc"));
		$.ajax({
			type:"POST", 
			url: context+"/op/sv/svItemAjaxXml.jsp",
			dataType:"json",  
			data:{
				"function" : "insertStatInfo",
				"dataCd" : $("#detailForm input[name='dataCd']").val(),
				"dataTypeCd" : $("#detailForm input[name='dataTypeCd']").val(),
				"useType" : $.cookie("useType"),
				"useDesc" : $.cookie("useDesc")
			},
			error:function(){   
				//console.log("예상치 못한 에러가 발생하였습니다.");   
			}, 
			success : function(data){
				location.href=updownUrl + "/OpenData/opDownloader.jsp?key="+fileData.key[0].text+"&filename="+fileData.fileNm[0].text;
				fileData=null;
				$.fn.closeLayer();
				//var dx = dx5.get("dext5");
				//dx5.get("dext5").download("AUTO", true);
			},
			complete : function(){
			}
		});		
	}else{
		openLayer('download_layer');
		$("#statArea").show();
	}
}


/*$.fn.dextDown = function(dataList){
var dx = dx5.get("dext5");

dx.setUIStyle({
 downloadButtonVisible: false
});

dx.setLimitMultiDownloadSize(1024 * 1024 * 300);

for(var i=0 ; i<dataList.length ; i++){
	var data=dataList[i];
	//console.log(data)
	dx.addVirtualFile({
	  vindex: "IDX"+i, 
	  // 인코딩 불필요
	  name: data.fileNmKr[0].text,
	  size: data.fileSize[0].text, 
	  // 인코딩 필요
	  downUrl: updownUrl + "/OpenData/opDownloader.jsp?key="+data.key[0].text+"&filename="+data.fileNm[0].text
	});
}


var statFlag=$.cookie("statFlag");
if(statFlag=='true'){
	$("#statArea").hide();
	setTimeout(function() {
		dx5.get("dext5").download("AUTO", true);
	}, 500);
}else{
	$("#statArea").show();
}
openLayer('download_layer');

}*/


$.fn.search = function(){
	$("#detailForm input[name='subCurrentPageNo']").val(1);
	
	//$("#detailForm input[name='dataTypeCd']").val($("#dataType").val());
	$("#detailForm input[name='dataStartDate']").val($("#startDate").val());
	$("#detailForm input[name='dataEndDate']").val($("#endDate").val());
	$("#detailForm").submit();
}







































