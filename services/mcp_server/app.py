#!/usr/bin/env python3
"""
MCP 서버 서비스 - Tool 실행 프록시, 컨텍스트 관리, 취소 기능
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# FastAPI 앱 생성
app = FastAPI(
    title="MCP 서버 서비스",
    description="Tool 실행 프록시, 컨텍스트 관리, 취소 기능",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서비스 설정
TOOL_REGISTRY_URL = "http://tool-registry:8005/tools"

# 실행 중인 작업 저장소
active_executions: Dict[str, Dict[str, Any]] = {}

# 데이터 모델
class MCPRequest(BaseModel):
    """MCP 요청 모델"""
    tool_name: str
    parameters: Dict[str, Any]
    context: Dict[str, Any] = {}

class MCPResponse(BaseModel):
    """MCP 응답 모델"""
    execution_id: str
    status: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

class ToolExecutionRequest(BaseModel):
    """도구 실행 요청 모델"""
    tool_id: str
    parameters: Dict[str, Any] = {}

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "MCP 서버 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.post("/execute")
async def execute_tool(request: ToolExecutionRequest, background_tasks: BackgroundTasks):
    """도구 실행"""
    # 실행 ID 생성
    execution_id = f"exec_{uuid.uuid4().hex[:8]}"
    
    # MCP 요청으로 변환
    mcp_request = MCPRequest(
        tool_name=request.tool_id,
        parameters=request.parameters,
        context={}
    )
    
    # 실행 정보 저장
    active_executions[execution_id] = {
        "tool_name": mcp_request.tool_name,
        "parameters": mcp_request.parameters,
        "context": mcp_request.context,
        "status": "running",
        "start_time": datetime.now().isoformat()
    }
    
    # 도구 실행을 백그라운드 작업으로 등록
    background_tasks.add_task(execute_tool_task, execution_id, mcp_request)
    
    return MCPResponse(
        execution_id=execution_id,
        status="accepted"
    )

@app.get("/status/{execution_id}")
async def get_execution_status(execution_id: str):
    """실행 상태 조회"""
    if execution_id not in active_executions:
        raise HTTPException(status_code=404, detail="실행 ID를 찾을 수 없습니다.")
    
    execution = active_executions[execution_id]
    
    return {
        "execution_id": execution_id,
        "status": execution["status"],
        "result": execution.get("result"),
        "error": execution.get("error")
    }

@app.post("/cancel/{execution_id}")
async def cancel_execution(execution_id: str):
    """실행 취소"""
    if execution_id not in active_executions:
        raise HTTPException(status_code=404, detail="실행 ID를 찾을 수 없습니다.")
    
    execution = active_executions[execution_id]
    
    if execution["status"] == "completed" or execution["status"] == "failed":
        raise HTTPException(status_code=400, detail="이미 완료되거나 실패한 실행은 취소할 수 없습니다.")
    
    # 실행 취소 처리
    execution["status"] = "cancelled"
    execution["end_time"] = datetime.now().isoformat()
    
    return {"status": "cancelled", "message": "실행이 취소되었습니다."}

# 백그라운드 작업
async def execute_tool_task(execution_id: str, request: MCPRequest):
    """도구 실행 작업"""
    try:
        # 도구 정보 조회
        tool_info = await get_tool_info(request.tool_name)
        
        if not tool_info:
            update_execution_status(execution_id, "failed", error=f"도구를 찾을 수 없습니다: {request.tool_name}")
            return
        
        # 도구 실행 (실제 구현에서는 도구 유형에 따라 다른 실행 방식 필요)
        result = await execute_tool_by_type(tool_info, request.parameters)
        
        # 실행 결과 업데이트
        update_execution_status(execution_id, "completed", result=result)
        
    except Exception as e:
        print(f"도구 실행 중 오류 발생: {str(e)}")
        update_execution_status(execution_id, "failed", error=str(e))

async def get_tool_info(tool_name: str) -> Optional[Dict[str, Any]]:
    """도구 정보 조회"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{TOOL_REGISTRY_URL}/{tool_name}")
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"도구 정보 조회 실패: {response.status_code} - {response.text}")
                return None
                
    except Exception as e:
        print(f"도구 정보 조회 중 오류 발생: {str(e)}")
        return None

async def execute_tool_by_type(tool_info: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    """도구 유형에 따른 실행"""
    tool_type = tool_info.get("tool_type", "unknown")
    
    # 간단한 예시 구현 (실제 구현에서는 더 복잡한 로직 필요)
    if tool_type == "car_diagnostic":
        return execute_car_diagnostic(parameters)
    elif tool_type == "maintenance_scheduler":
        return execute_maintenance_scheduler(parameters)
    else:
        return {"error": f"지원하지 않는 도구 유형: {tool_type}"}

def execute_car_diagnostic(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """자동차 진단 도구 실행"""
    # 실제 구현에서는 진단 로직 필요
    diagnostic_data = parameters.get("diagnostic_data", {})
    
    # 간단한 예시 결과
    return {
        "status": "normal",
        "issues": [],
        "recommendations": ["정기 점검을 계속 유지하세요."]
    }

def execute_maintenance_scheduler(parameters: Dict[str, Any]) -> Dict[str, Any]:
    """정비 일정 도구 실행"""
    # 실제 구현에서는 일정 관리 로직 필요
    maintenance_data = parameters.get("maintenance_data", {})
    
    # 간단한 예시 결과
    return {
        "next_available_slot": "2023-07-15T10:00:00",
        "estimated_duration": "2 hours",
        "estimated_cost": "₩150,000"
    }

def update_execution_status(execution_id: str, status: str, result: Dict[str, Any] = None, error: str = None):
    """실행 상태 업데이트"""
    if execution_id in active_executions:
        execution = active_executions[execution_id]
        execution["status"] = status
        execution["end_time"] = datetime.now().isoformat()
        
        if result:
            execution["result"] = result
        
        if error:
            execution["error"] = error

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8004, reload=True) 