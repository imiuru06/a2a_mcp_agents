#!/usr/bin/env python3
"""
수퍼바이저 서비스 - A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답
"""

import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import re
import logging
import json
import asyncio

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supervisor")

# FastAPI 앱 생성
app = FastAPI(
    title="수퍼바이저 서비스",
    description="A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답",
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
CHAT_GATEWAY_URL = os.getenv("CHAT_GATEWAY_URL", "http://chat-gateway:8002/responses")
AGENT_CARD_REGISTRY_URL = os.getenv("AGENT_CARD_REGISTRY_URL", "http://agent-card-registry:8006")
SUB_AGENT_URL = os.getenv("SUB_AGENT_URL", "http://sub-agent:8000/events")
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 1.0

# 상태 저장소
reports_store: Dict[str, Dict[str, Any]] = {}
messages_store: Dict[str, Dict[str, Any]] = {}
conversation_history: Dict[str, List[Dict[str, Any]]] = {}

# HTTP 클라이언트 생성
http_client = httpx.AsyncClient(timeout=10.0)

# 데이터 모델
class Report(BaseModel):
    """A2A 보고 모델"""
    report_id: str
    event_id: str
    agent_id: str
    status: str
    result: Dict[str, Any]
    timestamp: str

class UserResponse(BaseModel):
    """사용자 응답 모델"""
    client_id: str
    message: str
    response_type: str = "text"  # text, status, error
    data: Optional[Dict[str, Any]] = None

class Event(BaseModel):
    """이벤트 모델"""
    event_id: str
    event_type: str
    source: str
    data: Dict[str, Any]
    timestamp: str

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "수퍼바이저 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/reports")
async def receive_report(report: Report, background_tasks: BackgroundTasks):
    """Sub-Agent로부터 보고 수신"""
    try:
        # 보고 저장
        report_dict = report.dict()
        reports_store[report.report_id] = report_dict
        logger.info(f"보고 수신: report_id={report.report_id}, event_id={report.event_id}")
        
        # 보고 처리
        # event_id를 통해 client_id 찾기
        event_id = report.event_id
        client_id = None
        
        # 관련 메시지에서 client_id 찾기
        for msg_id, msg in messages_store.items():
            if msg.get("event_id") == event_id:
                client_id = msg.get("client_id")
                break
        
        # client_id가 없는 경우 데이터에서 찾기 시도
        if not client_id and "client_id" in report.result:
            client_id = report.result["client_id"]
        
        if client_id:
            if report.status == "completed":
                response_msg = generate_response_from_report(report)
                background_tasks.add_task(
                    send_response_to_user,
                    client_id, 
                    response_msg, 
                    "text"
                )
            else:
                background_tasks.add_task(
                    send_response_to_user,
                    client_id, 
                    "작업 처리 중 오류가 발생했습니다.", 
                    "error"
                )
        else:
            logger.warning(f"보고에 대한 client_id를 찾을 수 없음: report_id={report.report_id}")
        
        return {"status": "accepted"}
    except Exception as e:
        logger.error(f"보고 처리 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"보고 처리 중 오류 발생: {str(e)}")

def generate_response_from_report(report: Report) -> str:
    """보고서 데이터에서 사용자 응답 생성"""
    result = report.result
    
    if "diagnostic_result" in result:
        diagnostic_data = result["diagnostic_result"]
        if isinstance(diagnostic_data, dict) and "recommendations" in diagnostic_data:
            return f"진단 결과: {diagnostic_data['recommendations']}"
        
    if "maintenance_result" in result:
        maintenance_data = result["maintenance_result"]
        if isinstance(maintenance_data, dict) and "schedule" in maintenance_data:
            return f"정비 일정이 예약되었습니다: {maintenance_data['schedule']}"
    
    return "작업이 완료되었습니다."

@app.post("/messages")
async def receive_message(message: Dict[str, Any], background_tasks: BackgroundTasks):
    """Chat Gateway로부터 메시지 수신"""
    try:
        client_id = message.get("client_id")
        user_message = message.get("message", "")
        message_id = message.get("message_id", f"msg_{uuid.uuid4().hex[:8]}")
        
        logger.info(f"새 메시지 수신: message_id={message_id}, client_id={client_id}")
        
        # 메시지 저장
        stored_message = {
            "message_id": message_id,
            "client_id": client_id,
            "message": user_message,
            "timestamp": datetime.now().isoformat(),
            "status": "received",
            "role": "user"
        }
        
        messages_store[message_id] = stored_message
        
        # 대화 기록 업데이트
        if client_id not in conversation_history:
            conversation_history[client_id] = []
        
        conversation_history[client_id].append(stored_message)
        
        # 메시지 의도 분석 및 처리
        background_tasks.add_task(process_user_message, client_id, user_message)
        
        # 즉시 접수 확인 응답
        background_tasks.add_task(
            send_response_to_user,
            client_id,
            "메시지를 받았습니다. 처리 중입니다...",
            "status"
        )
        
        return {"status": "accepted", "message_id": message_id}
    except Exception as e:
        logger.error(f"메시지 수신 처리 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"메시지 처리 중 오류 발생: {str(e)}")

async def process_user_message(client_id: str, user_message: str):
    """사용자 메시지 처리 및 적절한 응답 생성"""
    try:
        logger.info(f"메시지 처리 시작: client_id={client_id}")
        
        # 메시지 의도 분석
        intent, entities = analyze_message_intent(user_message)
        logger.info(f"메시지 의도 분석 결과: intent={intent}, entities={entities}")
        
        # 적절한 에이전트 찾기
        agent = await find_appropriate_agent(intent)
        
        if "테스트" in user_message:
            # 테스트 메시지 특별 처리
            response = "테스트 메시지를 확인했습니다. 시스템이 정상 작동 중입니다."
        elif intent == "car_issue" and "엔진 오일" in user_message and "경고등" in user_message:
            # 엔진 오일 경고등 관련 응답
            response = generate_engine_oil_warning_response(entities)
        elif intent == "car_maintenance":
            # 일반 자동차 정비 관련 응답
            response = generate_car_maintenance_response(entities)
        elif intent == "car_diagnosis":
            # 자동차 진단 관련 이벤트 생성 및 처리
            event_id = f"event_{uuid.uuid4().hex[:8]}"
            await create_diagnostic_event(event_id, client_id, entities)
            response = "차량 진단을 요청했습니다. 잠시 후 결과를 알려드리겠습니다."
        else:
            # 기본 응답
            response = f"안녕하세요! 자동차 정비 서비스입니다. '{user_message}'에 대한 도움이 필요하시군요. 어떻게 도와드릴까요?"
        
        # 응답 저장
        response_id = f"resp_{uuid.uuid4().hex[:8]}"
        response_message = {
            "message_id": response_id,
            "client_id": client_id,
            "response": response,  # 'message' 대신 'response' 사용
            "timestamp": datetime.now().isoformat(),
            "status": "completed",
            "role": "assistant"
        }
        
        messages_store[client_id] = response_message
        conversation_history[client_id].append(response_message)
        
        logger.info(f"응답 생성 완료: client_id={client_id}, response_id={response_id}")
        
        # 사용자에게 응답 전송
        await send_response_to_user(client_id, response, "text")
        
    except Exception as e:
        logger.error(f"메시지 처리 중 오류 발생: client_id={client_id}, error={str(e)}")
        error_response = "죄송합니다. 메시지 처리 중 오류가 발생했습니다."
        await send_response_to_user(client_id, error_response, "error")

def analyze_message_intent(message: str) -> tuple:
    """메시지 의도 및 엔티티 분석"""
    # 간단한 의도 분석 로직 (실제로는 NLP 서비스나 정교한 분류기 사용 필요)
    intent = "general"
    entities = {}
    
    # 자동차 이슈 패턴
    car_issue_patterns = [
        r"경고등", r"불이 켜졌", r"고장", r"소리가 나", r"진동", 
        r"엔진", r"오작동", r"시동", r"브레이크", r"기름", r"오일"
    ]
    
    # 정비 관련 패턴
    maintenance_patterns = [
        r"정비", r"수리", r"점검", r"교체", r"예약", r"정기 점검",
        r"타이어", r"배터리", r"교환", r"정검", r"서비스", r"as"
    ]
    
    # 진단 관련 패턴
    diagnosis_patterns = [
        r"진단", r"검사", r"상태", r"체크", r"확인", r"문제가 뭔지"
    ]
    
    # 차량 유형 추출 시도
    car_type_patterns = [
        (r"([가-힣\s\d]+)\s?차량", "car_model"),
        (r"내 ([가-힣\s\d]+)", "car_model")
    ]
    
    # 자동차 이슈 확인
    for pattern in car_issue_patterns:
        if re.search(pattern, message, re.IGNORECASE):
            intent = "car_issue"
            # 특정 이슈 식별
            if "엔진 오일" in message or ("엔진" in message and "오일" in message):
                entities["issue_type"] = "engine_oil"
            elif "브레이크" in message:
                entities["issue_type"] = "brake"
            elif "타이어" in message:
                entities["issue_type"] = "tire"
            elif "배터리" in message:
                entities["issue_type"] = "battery"
            else:
                entities["issue_type"] = "general"
            break
    
    # 정비 관련 확인
    if intent == "general":  # 이전에 이슈로 식별되지 않은 경우만
        for pattern in maintenance_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                intent = "car_maintenance"
                break
    
    # 진단 관련 확인
    if intent == "general":  # 이전에 다른 의도로 식별되지 않은 경우만
        for pattern in diagnosis_patterns:
            if re.search(pattern, message, re.IGNORECASE):
                intent = "car_diagnosis"
                break
    
    # 차량 모델 추출 시도
    for pattern, entity_name in car_type_patterns:
        match = re.search(pattern, message)
        if match:
            entities[entity_name] = match.group(1)
            break
    
    return intent, entities

def generate_engine_oil_warning_response(entities: Dict[str, Any]) -> str:
    """엔진 오일 경고등 관련 응답 생성"""
    response = [
        "엔진 오일 경고등이 켜졌군요. 다음과 같이 조치해 보세요:",
        "",
        "1. 안전한 장소에 차를 정차하고 엔진을 끄세요.",
        "2. 엔진이 식은 후, 오일량을 확인하세요. 오일 게이지를 뽑아 레벨을 확인합니다.",
        "3. 오일량이 부족하면 적정 수준까지 보충하세요. (차량 매뉴얼에 맞는 오일을 사용하세요.)",
        "4. 오일량이 정상이라면 오일 품질이나 오일 센서에 문제가 있을 수 있습니다.",
        "",
        "가까운 정비소에서 점검받는 것을 권장합니다. 도움이 필요하시면 가까운 정비소를 추천해 드릴까요?"
    ]
    
    return "\n".join(response)

def generate_car_maintenance_response(entities: Dict[str, Any]) -> str:
    """자동차 정비 관련 응답 생성"""
    car_model = entities.get("car_model", "귀하의 차량")
    
    response = [
        f"{car_model}의 정비가 필요하시군요.",
        "",
        "다음 정비 항목 중 어떤 것이 필요하신가요?",
        "- 정기점검 (엔진 오일, 필터 교체 등)",
        "- 타이어 교체/점검",
        "- 브레이크 점검",
        "- 에어컨/히터 점검",
        "- 배터리 점검",
        "",
        "또는 정비 예약을 도와드릴까요? 원하시는 날짜와 시간을 알려주세요."
    ]
    
    return "\n".join(response)

async def create_diagnostic_event(event_id: str, client_id: str, entities: Dict[str, Any]):
    """차량 진단 이벤트 생성 및 전송"""
    try:
        event = Event(
            event_id=event_id,
            event_type="car_diagnostic",
            source="supervisor",
            data={
                "client_id": client_id,
                "diagnostic_data": {
                    "car_model": entities.get("car_model", "unknown"),
                    "issue_type": entities.get("issue_type", "general"),
                    "description": f"사용자 요청에 의한 진단: {entities}"
                }
            },
            timestamp=datetime.now().isoformat()
        )
        
        async with httpx.AsyncClient() as client:
            response = await client.post(SUB_AGENT_URL, json=event.dict())
            print(f"진단 이벤트 전송 결과: {response.status_code}")
            
    except Exception as e:
        print(f"진단 이벤트 생성 중 오류 발생: {str(e)}")

async def find_appropriate_agent(intent: str) -> Dict[str, Any]:
    """의도에 적합한 에이전트 찾기"""
    try:
        capabilities = []
        
        if intent == "car_issue":
            capabilities = ["car_troubleshooting", "engine_diagnostics"]
        elif intent == "car_maintenance":
            capabilities = ["car_maintenance", "service_scheduling"]
        elif intent == "car_diagnosis":
            capabilities = ["car_diagnostics", "sensor_analysis"]
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

async def send_response_to_user(client_id: str, message: str, response_type: str, data: Dict[str, Any] = None):
    """사용자에게 응답 전송"""
    try:
        # 로그 시작
        logger.info(f"사용자 응답 전송 시작: client_id={client_id}, type={response_type}")
        
        response = UserResponse(
            client_id=client_id,
            message=message,
            response_type=response_type,
            data=data
        )
        
        response_dict = response.dict(exclude_none=True)
        
        # 응답 저장
        if response_type == "text":
            response_id = f"resp_{uuid.uuid4().hex[:8]}"
            messages_store[response_id] = {
                "client_id": client_id,
                "response": message,
                "timestamp": datetime.now().isoformat()
            }
        
        # 재시도 로직으로 응답 전송
        for retry in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    logger.debug(f"응답 전송 시도 ({retry+1}/{MAX_RETRIES}): client_id={client_id}")
                    api_response = await client.post(
                        CHAT_GATEWAY_URL, 
                        json=response_dict,
                        timeout=10.0
                    )
                    
                    if api_response.status_code == 200:
                        logger.info(f"응답 전송 성공: client_id={client_id}")
                        return
                    else:
                        logger.warning(f"응답 전송 실패: client_id={client_id}, status_code={api_response.status_code}")
                        
                        # 마지막 시도가 아니면 재시도
                        if retry < MAX_RETRIES - 1:
                            logger.info(f"응답 전송 재시도 중 ({retry+1}/{MAX_RETRIES}): client_id={client_id}")
                            await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
                            
            except Exception as e:
                logger.error(f"응답 전송 중 오류 발생: client_id={client_id}, error={str(e)}")
                
                # 마지막 시도가 아니면 재시도
                if retry < MAX_RETRIES - 1:
                    logger.info(f"응답 전송 재시도 중 ({retry+1}/{MAX_RETRIES}): client_id={client_id}")
                    await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
                
    except Exception as e:
        logger.error(f"응답 전송 처리 중 오류 발생: client_id={client_id}, error={str(e)}")

@app.get("/responses/{client_id}")
async def get_response_by_client_id(client_id: str):
    """특정 클라이언트의 최신 응답 조회"""
    try:
        logger.info(f"클라이언트 응답 조회: client_id={client_id}")
        
        # 검색 결과를 저장할 리스트
        client_responses = []
        
        # 1. 직접 client_id를 키로 하는 응답 확인
        if client_id in messages_store:
            client_responses.append(messages_store[client_id])
        
        # 2. 모든 메시지 중에서 해당 클라이언트의 응답 검색
        for msg_id, msg in messages_store.items():
            if msg.get("client_id") == client_id and "response" in msg:
                client_responses.append(msg)
        
        # 3. 대화 기록에서 마지막 응답 찾기
        if client_id in conversation_history:
            assistant_messages = [msg for msg in conversation_history[client_id] if msg.get("role") == "assistant"]
            if assistant_messages:
                latest_assistant_msg = assistant_messages[-1]
                # response 형식으로 변환
                client_responses.append({
                    "client_id": client_id,
                    "response": latest_assistant_msg.get("message", latest_assistant_msg.get("response", "")),
                    "timestamp": latest_assistant_msg.get("timestamp", datetime.now().isoformat())
                })
        
        # 최신 응답 선택
        if client_responses:
            # 타임스탬프로 정렬 (최신 순)
            sorted_responses = sorted(
                client_responses, 
                key=lambda x: x.get("timestamp", ""), 
                reverse=True
            )
            latest_response = sorted_responses[0]
            
            # 응답이 없는지 확인
            if "response" not in latest_response and "message" in latest_response:
                latest_response["response"] = latest_response["message"]
                
            return latest_response
        
        # 응답이 없는 경우
        logger.warning(f"해당 클라이언트의 응답을 찾을 수 없음: client_id={client_id}")
        return {}
    
    except Exception as e:
        logger.error(f"응답 조회 중 오류 발생: client_id={client_id}, error={str(e)}")
        raise HTTPException(status_code=500, detail=f"응답 조회 중 오류 발생: {str(e)}")

async def register_service():
    """서비스 레지스트리에 등록"""
    service_data = {
        "name": "supervisor",
        "url": "http://supervisor:8003",
        "health_check_url": "http://supervisor:8003/health",
        "metadata": {
            "description": "수퍼바이저 서비스",
            "version": "1.0.0"
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(SERVICE_REGISTRY_URL, json=service_data)
            if response.status_code == 200:
                logger.info("서비스 레지스트리 등록 성공")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 등록 중 오류 발생: {str(e)}")

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 이벤트"""
    # 서비스 레지스트리 등록
    try:
        await register_service()
    except Exception as e:
        logger.error(f"시작 이벤트 중 오류 발생: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 이벤트"""
    await http_client.aclose()

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8003, reload=True)
