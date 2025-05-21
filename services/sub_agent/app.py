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
import random

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
AGENT_CARD_REGISTRY_URL = "http://agent-card-registry:8006"

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

# 차량 문제에 대한 권장 사항 데이터베이스
CAR_ISSUE_RECOMMENDATIONS = {
    "engine_oil": [
        {
            "severity": "low",
            "symptoms": ["경고등만 켜짐", "엔진 소음 없음"],
            "recommendations": [
                "오일량 확인: 오일 게이지를 사용하여 오일 레벨 확인",
                "적정 오일 보충: 부족한 경우 차량 매뉴얼에 맞는 오일로 보충",
                "오일 품질 확인: 오일이 검게 변했거나 점성이 낮아졌다면 교체 필요",
                "다음 정비소 방문 시 점검 요청"
            ]
        },
        {
            "severity": "medium",
            "symptoms": ["경고등 깜빡임", "약간의 엔진 소음", "엔진 성능 저하"],
            "recommendations": [
                "가능한 빨리 안전한 곳에 차량 정차",
                "엔진 오일량 즉시 확인",
                "오일 누수 점검: 차량 하부에 오일 흔적이 있는지 확인",
                "가까운 정비소에서 점검 권장 (1-2일 이내)",
                "장거리 운행 자제"
            ]
        },
        {
            "severity": "high",
            "symptoms": ["경고등 지속적 깜빡임", "심한 엔진 소음", "엔진 과열", "심각한 성능 저하"],
            "recommendations": [
                "즉시 안전한 곳에 차량 정차 후 엔진 끄기",
                "견인 서비스 요청 (직접 운전하지 말 것)",
                "긴급 정비 서비스 연락",
                "오일 압력 시스템 전체 점검 필요"
            ]
        }
    ],
    "brake": [
        {
            "severity": "medium",
            "recommendations": [
                "브레이크 패드 마모도 확인",
                "브레이크 액 레벨 점검",
                "가까운 정비소에서 브레이크 시스템 점검 권장"
            ]
        }
    ],
    "tire": [
        {
            "severity": "low",
            "recommendations": [
                "타이어 공기압 확인 및 조정",
                "타이어 마모도 확인",
                "필요시 타이어 로테이션 또는 교체"
            ]
        }
    ],
    "battery": [
        {
            "severity": "medium",
            "recommendations": [
                "배터리 단자 점검 및 청소",
                "배터리 충전 상태 확인",
                "필요시 배터리 교체"
            ]
        }
    ],
}

# 근처 정비소 데이터베이스 (샘플)
NEARBY_REPAIR_SHOPS = [
    {
        "name": "A+ 자동차 정비",
        "address": "서울시 강남구 역삼동 123-45",
        "phone": "02-123-4567",
        "rating": 4.5,
        "specialties": ["엔진 오일", "일반 정비"]
    },
    {
        "name": "현대 공식 서비스센터",
        "address": "서울시 서초구 방배동 789-12",
        "phone": "02-234-5678",
        "rating": 4.8,
        "specialties": ["현대/기아", "공식 정비"]
    },
    {
        "name": "24시간 긴급출동 정비소",
        "address": "서울시 송파구 잠실동 456-78",
        "phone": "02-345-6789",
        "rating": 4.2,
        "specialties": ["긴급 출동", "타이어", "배터리"]
    }
]

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
    # 진단 데이터 가져오기
    diagnostic_data = event.data.get("diagnostic_data", {})
    issue_type = diagnostic_data.get("issue_type", "general")
    car_model = diagnostic_data.get("car_model", "unknown")
    
    # 적절한 에이전트 검색
    agent = await find_appropriate_agent("car_diagnosis")
    
    # 이슈 유형에 따른 진단 수행
    if issue_type == "engine_oil":
        diagnostic_result = await diagnose_engine_oil_issue(car_model)
    elif issue_type == "brake":
        diagnostic_result = await diagnose_brake_issue(car_model)
    elif issue_type == "tire":
        diagnostic_result = await diagnose_tire_issue(car_model)
    elif issue_type == "battery":
        diagnostic_result = await diagnose_battery_issue(car_model)
    else:
        # 일반적인 진단
        diagnostic_result = await perform_general_diagnostic(car_model)
    
    # 근처 정비소 추가
    nearby_shops = get_nearby_repair_shops(issue_type)
    
    # 결과 포맷팅
    result = {
        "status": "completed",
        "agent_id": agent.get("id", "mechanic_agent"),
        "diagnostic_result": {
            "issue_type": issue_type,
            "car_model": car_model,
            "analysis": diagnostic_result["analysis"],
            "recommendations": diagnostic_result["recommendations"],
            "severity": diagnostic_result["severity"],
            "nearby_repair_shops": nearby_shops
        },
        "timestamp": datetime.now().isoformat()
    }
    
    return result

async def diagnose_engine_oil_issue(car_model: str) -> Dict[str, Any]:
    """엔진 오일 문제 진단"""
    # 진단 결과 (실제로는 더 정교한 진단 로직 필요)
    issue_data = random.choice(CAR_ISSUE_RECOMMENDATIONS["engine_oil"])
    severity = issue_data["severity"]
    
    if severity == "low":
        analysis = "엔진 오일 경고등이 켜졌으나 심각한 문제는 아닌 것으로 판단됩니다."
    elif severity == "medium":
        analysis = "엔진 오일 관련 잠재적 문제가 감지되었습니다. 빠른 점검이 필요합니다."
    else:
        analysis = "엔진 오일 시스템에 심각한 문제가 발견되었습니다. 즉시 조치가 필요합니다."
    
    return {
        "analysis": analysis,
        "recommendations": issue_data["recommendations"],
        "severity": severity
    }

async def diagnose_brake_issue(car_model: str) -> Dict[str, Any]:
    """브레이크 문제 진단"""
    issue_data = random.choice(CAR_ISSUE_RECOMMENDATIONS["brake"])
    return {
        "analysis": "브레이크 시스템에 잠재적 문제가 감지되었습니다.",
        "recommendations": issue_data["recommendations"],
        "severity": issue_data["severity"]
    }

async def diagnose_tire_issue(car_model: str) -> Dict[str, Any]:
    """타이어 문제 진단"""
    issue_data = random.choice(CAR_ISSUE_RECOMMENDATIONS["tire"])
    return {
        "analysis": "타이어 상태 점검이 필요합니다.",
        "recommendations": issue_data["recommendations"],
        "severity": issue_data["severity"]
    }

async def diagnose_battery_issue(car_model: str) -> Dict[str, Any]:
    """배터리 문제 진단"""
    issue_data = random.choice(CAR_ISSUE_RECOMMENDATIONS["battery"])
    return {
        "analysis": "배터리 시스템에 문제가 감지되었습니다.",
        "recommendations": issue_data["recommendations"],
        "severity": issue_data["severity"]
    }

async def perform_general_diagnostic(car_model: str) -> Dict[str, Any]:
    """일반 자동차 진단"""
    return {
        "analysis": "종합 진단 결과, 특별한 문제는 발견되지 않았습니다.",
        "recommendations": [
            "정기적인 점검 유지",
            "주행 중 이상 징후 발생 시 즉시 점검 필요"
        ],
        "severity": "low"
    }

def get_nearby_repair_shops(issue_type: str, limit: int = 3) -> List[Dict[str, Any]]:
    """근처 정비소 정보 가져오기"""
    # 실제로는 사용자 위치 기반으로 정비소 검색
    # 현재는 샘플 데이터 반환
    return NEARBY_REPAIR_SHOPS[:limit]

async def handle_maintenance_request(event: Event):
    """정비 요청 이벤트 처리"""
    # 정비 데이터 가져오기
    maintenance_data = event.data.get("maintenance_data", {})
    
    # 적절한 에이전트 검색
    agent = await find_appropriate_agent("car_maintenance")
    
    # MCP 서버를 통해 정비 도구 호출
    mcp_request = MCPRequest(
        tool_name="maintenance_scheduler_tool",
        parameters={"maintenance_data": maintenance_data},
        context={"event_id": event.event_id}
    )
    
    # MCP 서버 호출
    mcp_result = await call_mcp_server(mcp_request)
    
    # 샘플 정비 일정 생성
    maintenance_date = datetime.now().replace(hour=14, minute=0).isoformat()
    shop = random.choice(NEARBY_REPAIR_SHOPS)
    
    return {
        "status": "completed",
        "agent_id": agent.get("id", "mechanic_agent"),
        "maintenance_result": {
            "schedule": maintenance_date,
            "repair_shop": shop,
            "estimated_cost": "50,000원 ~ 100,000원",
            "estimated_duration": "1시간"
        },
        "timestamp": datetime.now().isoformat()
    }

async def find_appropriate_agent(intent: str) -> Dict[str, Any]:
    """의도에 적합한 에이전트 찾기"""
    try:
        capabilities = []
        
        if intent == "car_diagnosis":
            capabilities = ["car_diagnostics", "sensor_analysis"]
        elif intent == "car_maintenance":
            capabilities = ["car_maintenance", "service_scheduling"]
        else:
            capabilities = ["general_assistance"]
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{AGENT_CARD_REGISTRY_URL}/agents/find",
                json={"required_capabilities": capabilities}
            )
            
            if response.status_code == 200:
                agents = response.json()
                if agents:
                    return agents[0]  # 가장 첫 번째 매칭된 에이전트 선택
            
            # 기본 에이전트 정보
            return {
                "id": "mechanic_agent",
                "name": "정비사 에이전트",
                "capabilities": ["general_assistance"]
            }
                
    except Exception as e:
        print(f"에이전트 검색 중 오류 발생: {str(e)}")
        return {
            "id": "default_agent",
            "name": "기본 에이전트",
            "capabilities": ["general_assistance"]
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