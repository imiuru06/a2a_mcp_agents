#!/usr/bin/env python3
"""
수퍼바이저 서비스 - A2A 보고 수집, 상태 집계, 추가 의사결정, 사용자 응답
"""

import uuid
import os
from datetime import datetime
from typing import Dict, List, Optional, Any, TypedDict, Annotated, Sequence, Union, cast, Literal
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
import re
import logging
import json
import asyncio
from dotenv import load_dotenv

# LangGraph 및 관련 라이브러리 임포트
from langchain.schema import HumanMessage, AIMessage, SystemMessage, FunctionMessage
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import BaseMessage
import operator
from functools import partial

# 환경 변수 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("supervisor")

# 환경 변수에서 API 키 로드
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "https://your-resource-name.openai.azure.com/")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "")

# API 키가 없을 경우 경고
if not AZURE_OPENAI_API_KEY:
    logger.warning("AZURE_OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")

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
LLM_REGISTRY_URL = os.getenv("LLM_REGISTRY_URL", "http://llm-registry:8101")

# 재시도 설정
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "2.0"))

# 상태 저장소
reports_store: Dict[str, Dict[str, Any]] = {}
messages_store: Dict[str, List[Dict[str, Any]]] = {}
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

class SupervisorMessage(BaseModel):
    client_id: str
    message: str
    timestamp: str = None
    context: Dict[str, Any] = {}

class GraphState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    next: str

class AgentTool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any] = {}

# Azure OpenAI LLM 설정
def get_llm():
    return AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=AZURE_OPENAI_API_KEY,
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1000"))
    )

# 사용 가능한 도구 목록 가져오기
async def get_available_tools():
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{os.getenv('TOOL_REGISTRY_URL', 'http://tool-registry:8005/tools')}")
            if response.status_code == 200:
                tools = response.json()
                return [
                    AgentTool(
                        name=tool.get("name"),
                        description=tool.get("description"),
                        parameters=tool.get("parameters", {})
                    ) for tool in tools
                ]
            return []
    except Exception as e:
        logger.error(f"도구 목록 가져오기 오류: {str(e)}")
        return []

# 에이전트 카드 가져오기
async def get_agent_cards():
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{AGENT_CARD_REGISTRY_URL}/agents")
            if response.status_code == 200:
                return response.json()
            return []
    except Exception as e:
        logger.error(f"에이전트 카드 가져오기 오류: {str(e)}")
        return []

# LangGraph 노드 함수
async def retrieve_knowledge(state):
    """사용자 메시지에 관련된 지식 검색"""
    messages = state["messages"]
    last_message = messages[-1]
    
    if not isinstance(last_message, HumanMessage):
        return {"messages": messages}
    
    # 실제 구현에서는 벡터 데이터베이스 등에서 검색 수행
    query = last_message.content
    
    try:
        # 간단한 예시: 키워드 기반 응답
        knowledge = ""
        if "엔진 오일" in query:
            knowledge = "엔진 오일은 일반적으로 5,000~10,000km 주행 후 교체가 권장됩니다."
        elif "타이어" in query:
            knowledge = "타이어 공기압은 월 1회 이상 점검하는 것이 좋습니다."
        elif "브레이크" in query:
            knowledge = "브레이크 패드는 보통 30,000~70,000km 주행 시 교체가 필요합니다."
        
        if knowledge:
            messages.append(FunctionMessage(content=knowledge, name="retrieve_knowledge"))
    except Exception as e:
        logger.error(f"지식 검색 중 오류: {str(e)}")
    
    return {"messages": messages}

async def car_diagnostic_agent(state):
    """자동차 진단 에이전트 노드"""
    messages = state["messages"]
    
    llm = get_llm()
    system_prompt = """당신은 자동차 정비 전문가입니다. 
    사용자의 자동차 관련 문제를 진단하고, 적절한 정비 조언을 제공해주세요.
    한국어로 자세하고 친절하게, 자동차 전문 용어는 가능한 쉽게 설명해주세요."""
    
    messages_for_llm = [SystemMessage(content=system_prompt)] + messages
    
    response = await llm.ainvoke(messages_for_llm)
    messages.append(response)
    
    return {"messages": messages}

async def maintenance_advisor_agent(state):
    """정비 조언 에이전트 노드"""
    messages = state["messages"]
    
    llm = get_llm()
    system_prompt = """당신은 자동차 정비 어드바이저입니다.
    사용자에게 정비 일정, 비용, 자가 점검 방법 등에 대한 구체적인 조언을 제공해주세요.
    한국어로 친절하게, 가격 범위나 시간 추정치 등 실용적인 정보를 포함해주세요."""
    
    messages_for_llm = [SystemMessage(content=system_prompt)] + messages
    
    response = await llm.ainvoke(messages_for_llm)
    messages.append(response)
    
    return {"messages": messages}

async def decide_agent(state):
    """어떤 에이전트를 실행할지 결정하는 라우터 노드"""
    messages = state["messages"]
    last_human_message = None
    
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            last_human_message = message
            break
    
    if not last_human_message:
        return "car_diagnostic_agent"
    
    query = last_human_message.content.lower()
    
    # 간단한 라우팅 로직
    if "진단" in query or "문제" in query or "고장" in query or "경고등" in query:
        return "car_diagnostic_agent"
    elif "비용" in query or "정비소" in query or "점검" in query or "일정" in query:
        return "maintenance_advisor_agent"
    else:
        return "car_diagnostic_agent"  # 기본 에이전트

def create_agent_workflow():
    """LangGraph 워크플로우 생성"""
    # 그래프 상태 정의
    workflow = StateGraph(GraphState)
    
    # 지식 검색 노드
    workflow.add_node("retrieve_knowledge", retrieve_knowledge)
    
    # 에이전트 노드들
    workflow.add_node("car_diagnostic_agent", car_diagnostic_agent)
    workflow.add_node("maintenance_advisor_agent", maintenance_advisor_agent)
    
    # 분기 결정 노드
    workflow.add_router("decide_agent", decide_agent, [
        "car_diagnostic_agent", 
        "maintenance_advisor_agent"
    ])
    
    # 엣지 설정
    workflow.set_entry_point("retrieve_knowledge")
    workflow.add_edge("retrieve_knowledge", "decide_agent")
    workflow.add_edge("car_diagnostic_agent", END)
    workflow.add_edge("maintenance_advisor_agent", END)
    
    # 그래프 컴파일
    return workflow.compile()

# 워크플로우 인스턴스 생성
agent_workflow = create_agent_workflow()

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "수퍼바이저 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

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
async def process_message(message: SupervisorMessage):
    """메시지 처리 엔드포인트"""
    try:
        client_id = message.client_id
        user_message = message.message
        
        # 타임스탬프 추가
        if not message.timestamp:
            message.timestamp = datetime.now().isoformat()
        
        # 메시지 저장
        if client_id not in messages_store:
            messages_store[client_id] = []
        
        messages_store[client_id].append(message.dict())
        
        # 비동기 응답 처리 시작
        asyncio.create_task(process_and_respond(client_id, user_message, message.context))
        
        return {"status": "accepted", "client_id": client_id, "message": "메시지가 접수되었습니다."}
    
    except Exception as e:
        logger.error(f"메시지 처리 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"메시지 처리 중 오류: {str(e)}")

@app.get("/messages/{client_id}")
async def get_messages(client_id: str):
    """클라이언트의 메시지 이력 조회"""
    if client_id in messages_store:
        return {"client_id": client_id, "messages": messages_store[client_id]}
    return {"client_id": client_id, "messages": []}

@app.get("/responses/{client_id}")
async def get_response(client_id: str):
    """클라이언트의 응답 조회"""
    if client_id in responses_store:
        return {"client_id": client_id, "response": responses_store[client_id]}
    return {"client_id": client_id, "response": ""}

async def process_and_respond(client_id: str, user_message: str, context: Dict[str, Any] = {}):
    """메시지 처리 및 응답 생성 (비동기)"""
    try:
        # LangGraph 에이전트 실행
        messages = [HumanMessage(content=user_message)]
        
        # 이전 대화 이력이 있으면 추가
        if client_id in messages_store and len(messages_store[client_id]) > 1:
            for prev_msg in messages_store[client_id][:-1]:  # 마지막 메시지 제외
                if prev_msg.get("role") == "user":
                    messages.append(HumanMessage(content=prev_msg.get("message", "")))
                elif prev_msg.get("role") == "assistant":
                    messages.append(AIMessage(content=prev_msg.get("response", "")))
        
        # 에이전트 워크플로우 실행
        result = await agent_workflow.ainvoke({"messages": messages, "next": None})
        final_messages = result["messages"]
        
        # 마지막 AI 메시지 추출
        response_message = ""
        for msg in reversed(final_messages):
            if isinstance(msg, AIMessage):
                response_message = msg.content
                break
        
        if not response_message:
            response_message = "죄송합니다. 현재 응답을 생성할 수 없습니다."
        
        # 응답 저장
        responses_store[client_id] = response_message
        
        # 응답을 채팅 게이트웨이에도 전송
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response_data = {
                    "client_id": client_id,
                    "response": response_message,
                    "timestamp": datetime.now().isoformat()
                }
                
                await client.post(CHAT_GATEWAY_URL, json=response_data)
        except Exception as e:
            logger.error(f"채팅 게이트웨이 응답 전송 오류: {str(e)}")
        
        logger.info(f"클라이언트 {client_id}에 대한 응답 생성 완료")
        
    except Exception as e:
        logger.error(f"응답 생성 중 오류 발생: {str(e)}")
        # 오류 발생 시 기본 응답
        error_response = "죄송합니다. 요청을 처리하는 중에 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
        responses_store[client_id] = error_response
        
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                error_data = {
                    "client_id": client_id,
                    "response": error_response,
                    "timestamp": datetime.now().isoformat(),
                    "error": str(e)
                }
                
                await client.post(CHAT_GATEWAY_URL, json=error_data)
        except Exception as nested_e:
            logger.error(f"오류 응답 전송 중 추가 오류: {str(nested_e)}")

@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 이벤트"""
    # 서비스 등록
    try:
        service_data = {
            "name": "supervisor",
            "url": f"http://supervisor:8003",
            "health_check_url": f"http://supervisor:8003/health",
            "metadata": {
                "version": "1.1.0",
                "description": "A2A MCP Agent System의 수퍼바이저 서비스"
            }
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{SERVICE_REGISTRY_URL}",
                json=service_data
            )
            
            if response.status_code == 200:
                logger.info("Supervisor가 서비스 레지스트리에 등록되었습니다.")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 이벤트"""
    await http_client.aclose()

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8003, reload=True)
