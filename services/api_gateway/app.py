from fastapi import FastAPI, HTTPException, Request, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx
import os
import json
import logging
from typing import Dict, List, Optional, Any
import time
from pydantic import BaseModel
import asyncio
from datetime import datetime, timedelta

# 서비스 레지스트리 URL
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# API 키 설정 (실제 환경에선 더 강력한 인증 사용)
API_KEYS = os.getenv("API_KEYS", "test_key_1,test_key_2").split(",")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

app = FastAPI(title="API Gateway")

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 비동기 HTTP 클라이언트
http_client = httpx.AsyncClient(timeout=30.0)


# 서비스 정보 캐시
services_cache = {}
last_cache_update = 0
CACHE_TTL = 60  # 60초


class RouteConfig(BaseModel):
    path: str
    target_service: str
    target_path: str = None
    methods: List[str] = ["GET", "POST", "PUT", "DELETE"]
    require_auth: bool = True


# 라우트 설정 (실제로는 설정 파일에서 로드될 수 있음)
routes = [
    RouteConfig(path="/chat", target_service="chat-gateway", target_path="/"),
    RouteConfig(path="/events", target_service="event-gateway", target_path="/"),
    RouteConfig(path="/supervisor", target_service="supervisor", target_path="/"),
    RouteConfig(path="/tools", target_service="tool-registry", target_path="/"),
    RouteConfig(path="/agents", target_service="agent-card-registry", target_path="/"),
]


async def authenticate(request: Request) -> bool:
    """API 키를 통한 간단한 인증"""
    api_key = request.headers.get("x-api-key")
    if api_key and api_key in API_KEYS:
        return True
    return False


async def get_service_url(service_name: str) -> str:
    """서비스 레지스트리에서 서비스 URL 가져오기"""
    global services_cache, last_cache_update
    
    current_time = time.time()
    
    # 캐시 업데이트가 필요한지 확인
    if current_time - last_cache_update > CACHE_TTL:
        try:
            async with http_client as client:
                response = await client.get(f"{SERVICE_REGISTRY_URL}/discovery/{service_name}")
                
                if response.status_code == 200:
                    services = response.json()
                    if services:
                        # 첫 번째 서비스의 URL 사용 (추후 로드 밸런싱 적용 가능)
                        services_cache[service_name] = services[0]["url"]
                        last_cache_update = current_time
                    else:
                        logger.error(f"서비스 '{service_name}'를 찾을 수 없습니다.")
                        return None
                else:
                    logger.error(f"서비스 레지스트리 응답 오류: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")
            if service_name in services_cache:
                logger.warning(f"서비스 '{service_name}'에 대해 캐시된 URL 사용")
                return services_cache[service_name]
            return None
    
    return services_cache.get(service_name)


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def api_gateway(request: Request, path: str):
    """모든 요청을 처리하는 메인 라우트"""
    # 요청 경로 처리
    full_path = "/" + path
    
    # 요청 메서드
    method = request.method
    
    # 라우트 찾기
    target_route = None
    for route in routes:
        if full_path.startswith(route.path) and method in route.methods:
            target_route = route
            break
    
    if not target_route:
        return JSONResponse(
            status_code=404,
            content={"detail": f"라우트를 찾을 수 없습니다: {full_path}"}
        )
    
    # 인증 처리
    if target_route.require_auth:
        is_authenticated = await authenticate(request)
        if not is_authenticated:
            return JSONResponse(
                status_code=401, 
                content={"detail": "인증에 실패했습니다"}
            )
    
    # 대상 서비스의 URL 조회
    target_service_url = await get_service_url(target_route.target_service)
    
    if not target_service_url:
        return JSONResponse(
            status_code=503,
            content={"detail": f"서비스를 찾을 수 없습니다: {target_route.target_service}"}
        )
    
    # 대상 경로 결정
    target_path = full_path
    if target_route.target_path is not None:
        relative_path = full_path[len(target_route.path):]
        if not relative_path.startswith("/"):
            relative_path = "/" + relative_path
        target_path = target_route.target_path + relative_path
    
    # 요청 헤더 준비
    headers = dict(request.headers)
    # 필요 없는 헤더 제거
    headers.pop("host", None)
    
    # 타겟 URL 구성
    target_url = f"{target_service_url}{target_path}"
    
    try:
        # 요청 바디 가져오기
        body = await request.body()
        
        # 요청 전달
        async with http_client as client:
            response = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                content=body,
                follow_redirects=True
            )
            
            # 응답 헤더 준비
            response_headers = dict(response.headers)
            
            # 응답 반환
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers
            )
    except Exception as e:
        logger.error(f"요청 처리 중 오류 발생: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": f"요청 처리 중 오류가 발생했습니다: {str(e)}"}
        )


@app.on_event("startup")
async def startup_event():
    """애플리케이션 시작 시 이벤트"""
    # 서비스 등록
    try:
        service_data = {
            "name": "api-gateway",
            "url": f"http://api-gateway:8000",
            "health_check_url": f"http://api-gateway:8000/health",
            "metadata": {
                "version": "1.0",
                "description": "API Gateway for A2A-MCP system"
            }
        }
        
        async with http_client as client:
            response = await client.post(
                f"{SERVICE_REGISTRY_URL}",
                json=service_data
            )
            
            if response.status_code == 200:
                logger.info("API Gateway가 서비스 레지스트리에 등록되었습니다.")
            else:
                logger.error(f"서비스 레지스트리 등록 실패: {response.status_code}")
    except Exception as e:
        logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    """애플리케이션 종료 시 이벤트"""
    await http_client.aclose() 