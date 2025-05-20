#!/usr/bin/env python3
"""
서브 에이전트 서비스 - 이벤트 판단, MCP 호출, A2A 보고
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import json

# FastAPI 앱 생성
app = FastAPI(
    title="서브 에이전트 서비스",
    description="이벤트 판단, MCP 호출, A2A 보고",
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
MCP_SERVER_URL = "http://mcp-server:8004/execute"
SUPERVISOR_URL = "http://supervisor:8003/reports"

# 데이터 모델
class Event(BaseModel):
    """이벤트 모델"""
    event_id: str
    event_type: str
    source: str
    data: Dict[str, Any]
    timestamp: str

class MCPRequest(BaseModel):
    """MCP 요청 모델"""
    tool_name: str
    parameters: Dict[str, Any]
    context: Dict[str, Any] = {}

class Report(BaseModel):
    """A2A 보고 모델"""
    report_id: str
    event_id: str
    agent_id: str = "sub-agent"
    status: str
    result: Dict[str, Any]
    timestamp: str

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "서브 에이전트 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.post("/events")
async def receive_event(event: Event, background_tasks: BackgroundTasks):
    """이벤트 게이트웨이로부터 이벤트 수신"""
    # 이벤트 처리를 백그라운드 작업으로 등록
    background_tasks.add_task(process_event, event)
    
    return {"status": "accepted", "message": "이벤트가 처리 중입니다."}

# 백그라운드 작업
async def process_event(event: Event):
    """이벤트 처리"""
    try:
        print(f"이벤트 처리 시작: {event.event_id}")
        
        # 이벤트 타입에 따른 처리
        if event.event_type == "car_diagnostic":
            result = await handle_car_diagnostic(event)
        elif event.event_type == "maintenance_request":
            result = await handle_maintenance_request(event)
        else:
            result = {"status": "error", "message": f"알 수 없는 이벤트 타입: {event.event_type}"}
        
        # 처리 결과를 Supervisor에게 보고
        await send_report_to_supervisor(event.event_id, result)
        
    except Exception as e:
        print(f"이벤트 처리 중 오류 발생: {str(e)}")
        # 오류 보고
        await send_report_to_supervisor(
            event.event_id, 
            {"status": "error", "message": f"처리 중 오류 발생: {str(e)}"}
        )

async def handle_car_diagnostic(event: Event):
    """자동차 진단 이벤트 처리"""
    # MCP 서버를 통해 진단 도구 호출
    diagnostic_data = event.data.get("diagnostic_data", {})
    
    mcp_request = MCPRequest(
        tool_name="car_diagnostic_tool",
        parameters={"diagnostic_data": diagnostic_data},
        context={"event_id": event.event_id}
    )
    
    # MCP 서버 호출
    mcp_result = await call_mcp_server(mcp_request)
    
    return {
        "status": "completed",
        "diagnostic_result": mcp_result,
        "timestamp": datetime.now().isoformat()
    }

async def handle_maintenance_request(event: Event):
    """정비 요청 이벤트 처리"""
    # MCP 서버를 통해 정비 도구 호출
    maintenance_data = event.data.get("maintenance_data", {})
    
    mcp_request = MCPRequest(
        tool_name="maintenance_scheduler_tool",
        parameters={"maintenance_data": maintenance_data},
        context={"event_id": event.event_id}
    )
    
    # MCP 서버 호출
    mcp_result = await call_mcp_server(mcp_request)
    
    return {
        "status": "completed",
        "maintenance_result": mcp_result,
        "timestamp": datetime.now().isoformat()
    }

async def call_mcp_server(mcp_request: MCPRequest):
    """MCP 서버 호출"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(MCP_SERVER_URL, json=mcp_request.dict())
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"MCP 서버 호출 실패: {response.status_code} - {response.text}")
                return {"error": f"MCP 서버 호출 실패: {response.status_code}"}
                
    except Exception as e:
        print(f"MCP 서버 호출 중 오류 발생: {str(e)}")
        return {"error": f"MCP 서버 호출 중 오류 발생: {str(e)}"}

async def send_report_to_supervisor(event_id: str, result: Dict[str, Any]):
    """처리 결과를 Supervisor에게 보고"""
    try:
        report = Report(
            report_id=f"rep_{uuid.uuid4().hex[:8]}",
            event_id=event_id,
            status="completed" if "error" not in result else "error",
            result=result,
            timestamp=datetime.now().isoformat()
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(SUPERVISOR_URL, json=report.dict())
            
            if response.status_code != 200:
                print(f"Supervisor 보고 실패: {response.status_code} - {response.text}")
                
    except Exception as e:
        print(f"Supervisor 보고 중 오류 발생: {str(e)}")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True) 