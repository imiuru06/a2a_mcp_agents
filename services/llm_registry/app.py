#!/usr/bin/env python3
"""
LLM 레지스트리 서비스 - 여러 LLM 모델을 등록하고 관리하는 서비스
"""

import os
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union
from fastapi import FastAPI, HTTPException, Depends, Query, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import asyncio

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm_registry")

# FastAPI 앱 생성
app = FastAPI(
    title="LLM 레지스트리 서비스",
    description="다양한 LLM 서비스 등록 및 선택적 사용을 위한 레지스트리",
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
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# 상태 저장소
llm_services: Dict[str, Dict[str, Any]] = {}
llm_service_stats: Dict[str, Dict[str, Any]] = {}
default_llm_service_id = None

# 데이터 모델
class LLMServiceBase(BaseModel):
    """LLM 서비스 기본 모델"""
    name: str
    description: str
    provider: str
    model_name: str
    api_endpoint: str
    api_type: str = Field(..., description="OpenAI, Azure, Anthropic, HuggingFace 등")
    version: str = "1.0"
    capabilities: List[str] = []
    config: Dict[str, Any] = {}
    metadata: Dict[str, Any] = {}

class LLMServiceCreate(LLMServiceBase):
    """LLM 서비스 등록 모델"""
    api_key: Optional[str] = None
    is_default: bool = False

class LLMServiceUpdate(BaseModel):
    """LLM 서비스 업데이트 모델"""
    name: Optional[str] = None
    description: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    api_endpoint: Optional[str] = None
    api_type: Optional[str] = None
    version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    config: Optional[Dict[str, Any]] = None
    api_key: Optional[str] = None
    is_default: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class LLMServiceResponse(LLMServiceBase):
    """LLM 서비스 응답 모델"""
    id: str
    is_default: bool
    is_active: bool
    created_at: str
    updated_at: Optional[str] = None

class LLMRequest(BaseModel):
    """LLM 요청 모델"""
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    messages: List[Dict[str, str]]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    context: Optional[Dict[str, Any]] = {}
    stream: bool = False

class LLMResponse(BaseModel):
    """LLM 응답 모델"""
    id: str
    service_id: str
    service_name: str
    content: str
    usage: Dict[str, int]
    created_at: str

class StatsResponse(BaseModel):
    """통계 응답 모델"""
    total_requests: int
    successful_requests: int
    failed_requests: int
    average_latency: float
    token_usage: Dict[str, int]
    last_used: Optional[str] = None

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "LLM 레지스트리 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post("/services", response_model=LLMServiceResponse, status_code=201)
async def register_llm_service(service: LLMServiceCreate, background_tasks: BackgroundTasks):
    """새로운 LLM 서비스 등록"""
    global default_llm_service_id
    
    # 서비스 ID 생성
    service_id = f"llm_{uuid.uuid4().hex[:8]}"
    
    # 보안: API 키 암호화 또는 안전하게 저장해야 함 (여기서는 간소화)
    api_key = service.api_key
    
    # 서비스 데이터 준비
    service_data = {
        "id": service_id,
        "name": service.name,
        "description": service.description,
        "provider": service.provider,
        "model_name": service.model_name,
        "api_endpoint": service.api_endpoint,
        "api_type": service.api_type,
        "version": service.version,
        "capabilities": service.capabilities,
        "config": service.config,
        "api_key": api_key,  # 실제 구현에서는 암호화 필요
        "is_default": service.is_default,
        "is_active": True,
        "metadata": service.metadata,
        "created_at": datetime.now().isoformat(),
        "updated_at": None
    }
    
    # 서비스 저장
    llm_services[service_id] = service_data
    
    # 통계 초기화
    llm_service_stats[service_id] = {
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0, 
        "latency_sum": 0,
        "token_usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        },
        "last_used": None
    }
    
    # 기본 서비스 설정
    if service.is_default or default_llm_service_id is None:
        # 기존 기본 서비스가 있다면 해제
        if default_llm_service_id and default_llm_service_id in llm_services:
            llm_services[default_llm_service_id]["is_default"] = False
        
        # 새 서비스를 기본으로 설정
        default_llm_service_id = service_id
    
    # 서비스 레지스트리에 등록 (백그라운드 작업)
    background_tasks.add_task(register_with_service_registry, service_id, service.name)
    
    # 응답 생성 (API 키 제외)
    response_data = {k: v for k, v in service_data.items() if k != "api_key"}
    return response_data

@app.get("/services", response_model=List[LLMServiceResponse])
async def list_services(
    provider: Optional[str] = None,
    capability: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100
):
    """LLM 서비스 목록 조회"""
    # 필터링 로직
    filtered_services = []
    for service in llm_services.values():
        if provider and service["provider"] != provider:
            continue
        if capability and capability not in service["capabilities"]:
            continue
        if is_active is not None and service["is_active"] != is_active:
            continue
        
        # API 키 제외
        filtered_service = {k: v for k, v in service.items() if k != "api_key"}
        filtered_services.append(filtered_service)
    
    # 페이지네이션
    paginated_services = filtered_services[skip:skip+limit]
    
    return paginated_services

@app.get("/services/{service_id}", response_model=LLMServiceResponse)
async def get_service(service_id: str):
    """특정 LLM 서비스 조회"""
    if service_id not in llm_services:
        raise HTTPException(status_code=404, detail="LLM 서비스를 찾을 수 없습니다")
    
    # API 키 제외
    service_data = {k: v for k, v in llm_services[service_id].items() if k != "api_key"}
    return service_data

@app.put("/services/{service_id}", response_model=LLMServiceResponse)
async def update_service(service_id: str, service_update: LLMServiceUpdate):
    """LLM 서비스 정보 업데이트"""
    global default_llm_service_id
    
    if service_id not in llm_services:
        raise HTTPException(status_code=404, detail="LLM 서비스를 찾을 수 없습니다")
    
    service = llm_services[service_id]
    
    # 업데이트 가능한 필드 목록
    update_fields = [
        "name", "description", "provider", "model_name", "api_endpoint", 
        "api_type", "version", "capabilities", "config", "api_key", 
        "metadata", "is_active"
    ]
    
    # 필드 업데이트
    for field in update_fields:
        if hasattr(service_update, field) and getattr(service_update, field) is not None:
            service[field] = getattr(service_update, field)
    
    # 기본 서비스 업데이트
    if service_update.is_default is not None:
        # 기본 서비스로 설정
        if service_update.is_default:
            # 기존 기본 서비스가 있다면 해제
            if default_llm_service_id and default_llm_service_id in llm_services:
                llm_services[default_llm_service_id]["is_default"] = False
            
            # 새 서비스를 기본으로 설정
            service["is_default"] = True
            default_llm_service_id = service_id
        elif service["is_default"]:
            # 기본 서비스를 해제하는 경우
            service["is_default"] = False
            
            # 다른 기본 서비스 찾기
            default_candidates = [
                s_id for s_id, s in llm_services.items() 
                if s["is_active"] and s_id != service_id
            ]
            
            if default_candidates:
                # 첫 번째 활성 서비스를 기본으로 설정
                default_llm_service_id = default_candidates[0]
                llm_services[default_llm_service_id]["is_default"] = True
            else:
                default_llm_service_id = None
    
    # 업데이트 시간 갱신
    service["updated_at"] = datetime.now().isoformat()
    
    # API 키 제외
    response_data = {k: v for k, v in service.items() if k != "api_key"}
    return response_data

@app.delete("/services/{service_id}", status_code=204)
async def delete_service(service_id: str):
    """LLM 서비스 삭제"""
    global default_llm_service_id
    
    if service_id not in llm_services:
        raise HTTPException(status_code=404, detail="LLM 서비스를 찾을 수 없습니다")
    
    # 기본 서비스인 경우 처리
    if service_id == default_llm_service_id:
        # 다른 활성 서비스 찾기
        default_candidates = [
            s_id for s_id, s in llm_services.items() 
            if s["is_active"] and s_id != service_id
        ]
        
        if default_candidates:
            # 첫 번째 활성 서비스를 기본으로 설정
            default_llm_service_id = default_candidates[0]
            llm_services[default_llm_service_id]["is_default"] = True
        else:
            default_llm_service_id = None
    
    # 서비스 삭제
    del llm_services[service_id]
    
    # 통계 삭제
    if service_id in llm_service_stats:
        del llm_service_stats[service_id]
    
    return None

@app.post("/default/{service_id}", response_model=LLMServiceResponse)
async def set_default_service(service_id: str):
    """기본 LLM 서비스 설정"""
    global default_llm_service_id
    
    if service_id not in llm_services:
        raise HTTPException(status_code=404, detail="LLM 서비스를 찾을 수 없습니다")
    
    # 서비스가 활성 상태인지 확인
    if not llm_services[service_id]["is_active"]:
        raise HTTPException(status_code=400, detail="비활성 서비스는 기본 서비스로 설정할 수 없습니다")
    
    # 기존 기본 서비스가 있다면 해제
    if default_llm_service_id and default_llm_service_id in llm_services:
        llm_services[default_llm_service_id]["is_default"] = False
    
    # 새 서비스를 기본으로 설정
    llm_services[service_id]["is_default"] = True
    default_llm_service_id = service_id
    
    # API 키 제외
    service_data = {k: v for k, v in llm_services[service_id].items() if k != "api_key"}
    return service_data

@app.get("/default", response_model=LLMServiceResponse)
async def get_default_service():
    """기본 LLM 서비스 조회"""
    if not default_llm_service_id or default_llm_service_id not in llm_services:
        raise HTTPException(status_code=404, detail="기본 LLM 서비스가 설정되지 않았습니다")
    
    # API 키 제외
    service_data = {k: v for k, v in llm_services[default_llm_service_id].items() if k != "api_key"}
    return service_data

@app.post("/generate", response_model=LLMResponse)
async def generate_llm_response(request: LLMRequest):
    """LLM을 사용하여 응답 생성"""
    # 서비스 선택
    service_id = await resolve_service_id(request.service_id, request.service_name)
    
    if not service_id:
        raise HTTPException(status_code=404, detail="적합한 LLM 서비스를 찾을 수 없습니다")
    
    # 서비스 정보 가져오기
    service = llm_services[service_id]
    
    # 요청 ID 생성
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    
    # 시작 시간 기록
    start_time = datetime.now()
    
    try:
        # LLM API 호출
        response_data = await call_llm_api(
            service, 
            request.messages, 
            request.temperature, 
            request.max_tokens,
            request.stream
        )
        
        # 종료 시간 기록 및 지연 시간 계산
        end_time = datetime.now()
        latency = (end_time - start_time).total_seconds()
        
        # 사용량 정보
        usage = response_data.get("usage", {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        })
        
        # 통계 업데이트
        update_service_stats(
            service_id, 
            True, 
            latency, 
            usage
        )
        
        # 응답 생성
        llm_response = {
            "id": request_id,
            "service_id": service_id,
            "service_name": service["name"],
            "content": response_data.get("content", ""),
            "usage": usage,
            "created_at": end_time.isoformat()
        }
        
        return llm_response
        
    except Exception as e:
        # 오류 로깅
        logger.error(f"LLM API 호출 중 오류 발생: {str(e)}")
        
        # 통계 업데이트 (실패)
        update_service_stats(service_id, False, 0, {"total_tokens": 0})
        
        # 오류 응답
        raise HTTPException(status_code=500, detail=f"LLM 응답 생성 중 오류: {str(e)}")

@app.get("/stats/{service_id}", response_model=StatsResponse)
async def get_service_stats(service_id: str):
    """특정 LLM 서비스의 통계 조회"""
    if service_id not in llm_service_stats:
        raise HTTPException(status_code=404, detail="LLM 서비스 통계를 찾을 수 없습니다")
    
    stats = llm_service_stats[service_id]
    
    # 평균 지연 시간 계산
    avg_latency = 0
    if stats["total_requests"] > 0:
        avg_latency = stats["latency_sum"] / stats["total_requests"]
    
    return {
        "total_requests": stats["total_requests"],
        "successful_requests": stats["successful_requests"],
        "failed_requests": stats["failed_requests"],
        "average_latency": round(avg_latency, 3),
        "token_usage": stats["token_usage"],
        "last_used": stats["last_used"]
    }

# 유틸리티 함수
async def resolve_service_id(service_id: Optional[str], service_name: Optional[str]) -> Optional[str]:
    """서비스 ID 해결: ID, 이름 또는 기본값 사용"""
    # ID가 제공된 경우
    if service_id and service_id in llm_services:
        return service_id
    
    # 이름이 제공된 경우
    if service_name:
        for s_id, service in llm_services.items():
            if service["name"] == service_name and service["is_active"]:
                return s_id
    
    # 기본 서비스 사용
    if default_llm_service_id and default_llm_service_id in llm_services:
        return default_llm_service_id
    
    # 활성 서비스 중 첫 번째 사용
    active_services = [s_id for s_id, s in llm_services.items() if s["is_active"]]
    if active_services:
        return active_services[0]
    
    return None

async def call_llm_api(
    service: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    temperature: float,
    max_tokens: int,
    stream: bool
) -> Dict[str, Any]:
    """LLM API 호출"""
    api_type = service["api_type"]
    
    if api_type == "openai":
        return await call_openai_api(service, messages, temperature, max_tokens, stream)
    elif api_type == "azure":
        return await call_azure_openai_api(service, messages, temperature, max_tokens, stream)
    elif api_type == "anthropic":
        return await call_anthropic_api(service, messages, temperature, max_tokens, stream)
    elif api_type == "huggingface":
        return await call_huggingface_api(service, messages, temperature, max_tokens)
    else:
        raise ValueError(f"지원하지 않는 API 유형: {api_type}")

async def call_openai_api(
    service: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    temperature: float,
    max_tokens: int,
    stream: bool
) -> Dict[str, Any]:
    """OpenAI API 호출"""
    api_endpoint = service["api_endpoint"]
    api_key = service["api_key"]
    model = service["model_name"]
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            raise Exception(f"OpenAI API 오류: {response.status_code} - {response.text}")
        
        response_data = response.json()
        
        return {
            "content": response_data["choices"][0]["message"]["content"],
            "usage": response_data.get("usage", {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            })
        }

async def call_azure_openai_api(
    service: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    temperature: float,
    max_tokens: int,
    stream: bool
) -> Dict[str, Any]:
    """Azure OpenAI API 호출"""
    api_endpoint = service["api_endpoint"]
    api_key = service["api_key"]
    
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }
    
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            raise Exception(f"Azure OpenAI API 오류: {response.status_code} - {response.text}")
        
        response_data = response.json()
        
        return {
            "content": response_data["choices"][0]["message"]["content"],
            "usage": response_data.get("usage", {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            })
        }

async def call_anthropic_api(
    service: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    temperature: float,
    max_tokens: int,
    stream: bool
) -> Dict[str, Any]:
    """Anthropic API 호출"""
    api_endpoint = service["api_endpoint"]
    api_key = service["api_key"]
    model = service["model_name"]
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    
    # Anthropic 형식으로 메시지 변환
    anthropic_messages = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "assistant"
        anthropic_messages.append({"role": role, "content": msg["content"]})
    
    payload = {
        "model": model,
        "messages": anthropic_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": stream
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            raise Exception(f"Anthropic API 오류: {response.status_code} - {response.text}")
        
        response_data = response.json()
        
        # Anthropic 응답 형식에 맞게 변환
        usage = {
            "prompt_tokens": response_data.get("usage", {}).get("input_tokens", 0),
            "completion_tokens": response_data.get("usage", {}).get("output_tokens", 0),
            "total_tokens": response_data.get("usage", {}).get("input_tokens", 0) + 
                           response_data.get("usage", {}).get("output_tokens", 0)
        }
        
        return {
            "content": response_data["content"][0]["text"],
            "usage": usage
        }

async def call_huggingface_api(
    service: Dict[str, Any], 
    messages: List[Dict[str, str]], 
    temperature: float,
    max_tokens: int
) -> Dict[str, Any]:
    """HuggingFace API 호출"""
    api_endpoint = service["api_endpoint"]
    api_key = service["api_key"]
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    # 메시지를 단일 프롬프트로 변환
    prompt = ""
    for msg in messages:
        role = "User" if msg["role"] == "user" else "Assistant"
        prompt += f"{role}: {msg['content']}\n"
    prompt += "Assistant: "
    
    payload = {
        "inputs": prompt,
        "parameters": {
            "temperature": temperature,
            "max_new_tokens": max_tokens,
            "return_full_text": False
        }
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            api_endpoint,
            headers=headers,
            json=payload,
            timeout=60.0
        )
        
        if response.status_code != 200:
            raise Exception(f"HuggingFace API 오류: {response.status_code} - {response.text}")
        
        response_data = response.json()
        
        # 대략적인 토큰 사용량 추정 (문자 수 / 4)
        prompt_tokens = len(prompt) // 4
        completion_text = response_data[0].get("generated_text", "")
        completion_tokens = len(completion_text) // 4
        
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens
        }
        
        return {
            "content": completion_text,
            "usage": usage
        }

def update_service_stats(
    service_id: str, 
    success: bool, 
    latency: float,
    usage: Dict[str, int]
):
    """서비스 통계 업데이트"""
    if service_id not in llm_service_stats:
        return
    
    stats = llm_service_stats[service_id]
    
    # 기본 통계 업데이트
    stats["total_requests"] += 1
    
    if success:
        stats["successful_requests"] += 1
        stats["latency_sum"] += latency
        
        # 토큰 사용량 업데이트
        stats["token_usage"]["prompt_tokens"] += usage.get("prompt_tokens", 0)
        stats["token_usage"]["completion_tokens"] += usage.get("completion_tokens", 0)
        stats["token_usage"]["total_tokens"] += usage.get("total_tokens", 0)
    else:
        stats["failed_requests"] += 1
    
    # 마지막 사용 시간 업데이트
    stats["last_used"] = datetime.now().isoformat()

async def register_with_service_registry(service_id: str, service_name: str):
    """서비스 레지스트리에 LLM 서비스 등록"""
    try:
        service_data = {
            "name": f"llm-{service_name}",
            "url": f"http://llm-registry:8101/services/{service_id}",
            "health_check_url": "http://llm-registry:8101/health",
            "metadata": {
                "type": "llm_service",
                "description": f"LLM 서비스: {service_name}",
                "service_id": service_id
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                SERVICE_REGISTRY_URL,
                json=service_data
            )
            
            if response.status_code == 200:
                logger.info(f"LLM 서비스가 서비스 레지스트리에 등록되었습니다: {service_id}")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")

# 서버 시작 이벤트
@app.on_event("startup")
async def startup_event():
    """서버 시작 시 실행"""
    logger.info("LLM 레지스트리 서비스 시작")

# 서버 종료 이벤트
@app.on_event("shutdown")
async def shutdown_event():
    """서버 종료 시 실행"""
    logger.info("LLM 레지스트리 서비스 종료")

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8101, reload=True) 