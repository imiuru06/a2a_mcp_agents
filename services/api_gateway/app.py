from fastapi import FastAPI, HTTPException, Request, Response, Depends, status, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
import httpx
import os
import json
import logging
from typing import Dict, List, Optional, Any
import time
from pydantic import BaseModel
import asyncio
from datetime import datetime, timedelta
import uuid
import shutil
from pathlib import Path

# 서비스 레지스트리 URL
SERVICE_REGISTRY_URL = os.getenv("SERVICE_REGISTRY_URL", "http://service-registry:8007/services")

# API 키 설정 (실제 환경에선 더 강력한 인증 사용)
API_KEYS = os.getenv("API_KEYS", "test_key_1,test_key_2").split(",")

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

# 업로드 파일 저장 디렉토리
UPLOAD_DIR = Path("/app/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="API Gateway",
    description="자동차 정비 서비스를 위한 API 게이트웨이",
    version="1.1.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 서비스 정보 캐시
services_cache = {}
last_cache_update = 0
CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))  # 60초
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30.0"))  # 요청 타임아웃 (초)


class RouteConfig(BaseModel):
    path: str
    target_service: str
    target_path: str = None
    methods: List[str] = ["GET", "POST", "PUT", "DELETE"]
    require_auth: bool = True


# 라우트 설정 (실제로는 설정 파일에서 로드될 수 있음)
routes = [
    RouteConfig(path="/chat", target_service="chat-gateway", target_path="/"),
    RouteConfig(path="/chat/messages", target_service="chat-gateway", target_path="/messages", require_auth=False),
    RouteConfig(path="/events", target_service="event-gateway", target_path="/"),
    RouteConfig(path="/events/", target_service="event-gateway", target_path="/", require_auth=False),
    RouteConfig(path="/supervisor", target_service="supervisor", target_path="/"),
    RouteConfig(path="/supervisor/responses", target_service="supervisor", target_path="/responses", require_auth=False),
    RouteConfig(path="/supervisor/messages", target_service="supervisor", target_path="/messages", require_auth=False),
    RouteConfig(path="/tools", target_service="tool-registry", target_path="/"),
    RouteConfig(path="/agents", target_service="agent-card-registry", target_path="/"),
    RouteConfig(path="/mcp", target_service="mcp-server", target_path="/"),
    RouteConfig(path="/ui/tools", target_service="tool-registry", target_path="/tools", require_auth=False),
    RouteConfig(path="/ui/agents", target_service="agent-card-registry", target_path="/agents", require_auth=False),
    RouteConfig(path="/ui/capabilities", target_service="agent-card-registry", target_path="/capabilities", require_auth=False),
    RouteConfig(path="/ui/execute-tool", target_service="mcp-server", target_path="/execute", require_auth=False),
    RouteConfig(path="/ui/status", target_service="mcp-server", target_path="/status", require_auth=False),
    RouteConfig(path="/ui/llm/services", target_service="llm-registry", target_path="/services", require_auth=False),
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
    
    # 서비스가 캐시에 있고 캐시가 유효하면 바로 반환
    if service_name in services_cache and current_time - last_cache_update <= CACHE_TTL:
        return services_cache[service_name]
    
    # 캐시 업데이트 시도
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{SERVICE_REGISTRY_URL}/discovery/{service_name}")
            
            if response.status_code == 200:
                services = response.json()
                if services:
                    # 첫 번째 서비스의 URL 사용 (추후 로드 밸런싱 적용 가능)
                    services_cache[service_name] = services[0]["url"]
                    last_cache_update = current_time
                    return services_cache[service_name]
                else:
                    logger.error(f"서비스 '{service_name}'를 찾을 수 없습니다.")
                    
                    # 하드코딩된 서비스 URL로 폴백 (개발 환경용)
                    fallback_urls = {
                        "chat-gateway": "http://chat-gateway:8002",
                        "event-gateway": "http://event-gateway:8001",
                        "supervisor": "http://supervisor:8003",
                        "tool-registry": "http://tool-registry:8005",
                        "agent-card-registry": "http://agent-card-registry:8006",
                        "mcp-server": "http://mcp-server:8004",
                        "llm-registry": "http://llm-registry:8101"
                    }
                    
                    if service_name in fallback_urls:
                        logger.warning(f"서비스 '{service_name}'에 대해 폴백 URL 사용")
                        services_cache[service_name] = fallback_urls[service_name]
                        return fallback_urls[service_name]
                    
                    return None
            else:
                logger.error(f"서비스 레지스트리 응답 오류: {response.status_code}")
                # 캐시에 있으면 캐시된 값을 사용
                if service_name in services_cache:
                    logger.warning(f"서비스 '{service_name}'에 대해 캐시된 URL 사용")
                    return services_cache[service_name]
                return None
    except Exception as e:
        logger.error(f"서비스 레지스트리 연결 오류: {str(e)}")
        if service_name in services_cache:
            logger.warning(f"서비스 '{service_name}'에 대해 캐시된 URL 사용")
            return services_cache[service_name]
        
        # 서비스 레지스트리 연결 실패 시 하드코딩된 값 반환
        fallback_urls = {
            "chat-gateway": "http://chat-gateway:8002",
            "event-gateway": "http://event-gateway:8001",
            "supervisor": "http://supervisor:8003",
            "tool-registry": "http://tool-registry:8005",
            "agent-card-registry": "http://agent-card-registry:8006",
            "mcp-server": "http://mcp-server:8004",
            "llm-registry": "http://llm-registry:8101"
        }
        
        if service_name in fallback_urls:
            logger.warning(f"서비스 레지스트리 연결 실패, '{service_name}'에 대해 폴백 URL 사용")
            return fallback_urls[service_name]
        
        return None


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트"""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/services")
async def list_all_services():
    """사용 가능한 모든 서비스 목록 반환"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(SERVICE_REGISTRY_URL)
            
            if response.status_code == 200:
                services = response.json()
                return {"services": services}
            else:
                raise HTTPException(status_code=response.status_code, detail="서비스 목록을 가져오는 중 오류 발생")
    except Exception as e:
        logger.error(f"서비스 목록 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"서비스 목록 조회 중 오류 발생: {str(e)}")


@app.get("/ui/dashboard")
async def get_dashboard_data():
    """UI 대시보드에 필요한 데이터를 통합하여 제공"""
    try:
        dashboard_data = {
            "agents": [],
            "tools": [],
            "capabilities": [],
            "active_services": []
        }
        
        # 1. 에이전트 목록 조회
        agent_service_url = await get_service_url("agent-card-registry")
        if agent_service_url:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(f"{agent_service_url}/agents")
                if response.status_code == 200:
                    dashboard_data["agents"] = response.json()
                    
        # 2. 도구 목록 조회
        tool_service_url = await get_service_url("tool-registry")
        if tool_service_url:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(f"{tool_service_url}/tools")
                if response.status_code == 200:
                    dashboard_data["tools"] = response.json()
        
        # 3. 기능(Capability) 목록 조회
        if agent_service_url:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.get(f"{agent_service_url}/capabilities")
                if response.status_code == 200:
                    dashboard_data["capabilities"] = response.json()
        
        # 4. 활성 서비스 목록
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(SERVICE_REGISTRY_URL)
            if response.status_code == 200:
                dashboard_data["active_services"] = response.json()
        
        return dashboard_data
    
    except Exception as e:
        logger.error(f"대시보드 데이터 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"대시보드 데이터 조회 중 오류 발생: {str(e)}")


@app.get("/ui/diagnostic-stats")
async def get_diagnostic_stats():
    """자동차 진단 통계 데이터 제공"""
    # 이 함수는 실제로 데이터를 가져오는 로직이 필요합니다.
    # 현재는 예시 데이터를 반환합니다.
    return {
        "total_diagnostics": 150,
        "issue_types": {
            "엔진 오일": 45,
            "브레이크": 28,
            "배터리": 32,
            "타이어": 21,
            "기타": 24
        },
        "severity_distribution": {
            "낮음": 67,
            "중간": 53,
            "높음": 30
        },
        "weekly_trend": [23, 18, 25, 19, 22, 28, 15]
    }


@app.get("/ui/mechanic-stats")
async def get_mechanic_stats():
    """정비사 에이전트 활동 통계 제공"""
    # 예시 데이터 반환
    return {
        "active_mechanics": 5,
        "total_appointments": 87,
        "service_areas": ["서울", "인천", "부산", "대구", "광주"],
        "specialty_distribution": {
            "엔진": 2,
            "전기": 1,
            "일반 정비": 1,
            "타이어/휠": 1
        },
        "service_ratings": 4.7
    }


@app.get("/ui/tool-usage")
async def get_tool_usage_stats():
    """도구 사용 현황 통계 제공"""
    # 예시 데이터 반환
    return {
        "most_used_tools": [
            {"name": "car_diagnostic_tool", "count": 178},
            {"name": "maintenance_scheduler_tool", "count": 92},
            {"name": "mechanic_finder_tool", "count": 65},
            {"name": "vehicle_manual_tool", "count": 43},
            {"name": "part_inventory_tool", "count": 21}
        ],
        "success_rate": {
            "car_diagnostic_tool": 0.94,
            "maintenance_scheduler_tool": 0.89,
            "mechanic_finder_tool": 0.92,
            "vehicle_manual_tool": 0.88,
            "part_inventory_tool": 0.85
        },
        "average_response_time": {
            "car_diagnostic_tool": 1.2,
            "maintenance_scheduler_tool": 0.8,
            "mechanic_finder_tool": 2.1,
            "vehicle_manual_tool": 0.9,
            "part_inventory_tool": 1.5
        }
    }


@app.post("/ui/execute-tool")
async def execute_tool_ui(request: Request):
    """UI를 통해 도구 직접 실행 (편의성 제공)"""
    try:
        # 요청 바디 파싱
        body = await request.json()
        
        tool_id = body.get("tool_id")
        parameters = body.get("parameters", {})
        
        if not tool_id:
            raise HTTPException(status_code=400, detail="tool_id는 필수 항목입니다")
            
        # MCP 서버에 요청 전달
        mcp_server_url = await get_service_url("mcp-server")
        if not mcp_server_url:
            raise HTTPException(status_code=503, detail="MCP 서버를 찾을 수 없습니다")
        
        # 요청 데이터 구성
        execution_request = {
            "tool_id": tool_id,
            "parameters": parameters,
            "llm_service_id": body.get("llm_service_id"),
            "llm_service_name": body.get("llm_service_name")
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{mcp_server_url}/execute", 
                json=execution_request
            )
            
            return response.json()
            
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"도구 실행 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"도구 실행 중 오류 발생: {str(e)}")


@app.post("/ui/files/upload")
async def upload_file(file: UploadFile = File(...)):
    """파일 업로드 처리"""
    try:
        # 고유한 파일명 생성
        file_id = str(uuid.uuid4())
        file_extension = os.path.splitext(file.filename)[1]
        new_filename = f"{file_id}{file_extension}"
        
        # 파일 저장
        file_path = UPLOAD_DIR / new_filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # 파일 정보 반환
        return {
            "file_id": file_id,
            "original_filename": file.filename,
            "stored_filename": new_filename,
            "content_type": file.content_type,
            "file_size": os.path.getsize(file_path),
            "upload_timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"파일 업로드 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 업로드 중 오류 발생: {str(e)}")


@app.get("/ui/files/{file_id}")
async def get_file(file_id: str):
    """업로드된 파일 조회"""
    try:
        # 파일 찾기
        files = list(UPLOAD_DIR.glob(f"{file_id}*"))
        if not files:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        file_path = files[0]
        
        # 파일 반환
        return FileResponse(
            path=file_path,
            filename=os.path.basename(file_path),
            media_type="application/octet-stream"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"파일 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 조회 중 오류 발생: {str(e)}")


@app.delete("/ui/files/{file_id}")
async def delete_file(file_id: str):
    """업로드된 파일 삭제"""
    try:
        # 파일 찾기
        files = list(UPLOAD_DIR.glob(f"{file_id}*"))
        if not files:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        file_path = files[0]
        
        # 파일 삭제
        os.remove(file_path)
        
        return {"status": "success", "message": "파일이 삭제되었습니다"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"파일 삭제 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 삭제 중 오류 발생: {str(e)}")


@app.post("/ui/analyze-file/{file_id}")
async def analyze_file(file_id: str):
    """업로드된 파일 분석"""
    try:
        # 파일 찾기
        files = list(UPLOAD_DIR.glob(f"{file_id}*"))
        if not files:
            raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다")
        
        file_path = files[0]
        file_extension = os.path.splitext(file_path)[1].lower()
        
        # 파일 유형에 따른 분석
        # 실제 구현에서는 적절한 서비스로 분석 요청을 전달해야 함
        if file_extension in ['.jpg', '.jpeg', '.png']:
            # 이미지 분석 예시
            analysis_result = {
                "file_type": "image",
                "analysis": {
                    "detected_objects": ["car", "wheel", "brake"],
                    "condition": "brake pad wear detected",
                    "recommendation": "brake pad replacement recommended"
                }
            }
        elif file_extension == '.pdf':
            # PDF 문서 분석 예시
            analysis_result = {
                "file_type": "document",
                "analysis": {
                    "document_type": "service manual",
                    "relevant_sections": ["brake system", "maintenance schedule"],
                    "extracted_text_sample": "Regular brake inspection recommended every 10,000 km"
                }
            }
        else:
            analysis_result = {
                "file_type": "unknown",
                "analysis": {
                    "message": "This file type is not supported for analysis"
                }
            }
            
        return {
            "file_id": file_id,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "analysis_result": analysis_result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"파일 분석 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"파일 분석 중 오류 발생: {str(e)}")


@app.get("/ui/chat-templates")
async def get_chat_templates():
    """채팅 템플릿 목록 제공"""
    templates = [
        {
            "id": "engine_oil",
            "title": "엔진 오일 교체",
            "content": "엔진 오일을 교체해야 할 때인가요?"
        },
        {
            "id": "tire_pressure",
            "title": "타이어 공기압 확인",
            "content": "타이어 공기압은 어떻게 확인하나요?"
        },
        {
            "id": "brake_pad",
            "title": "브레이크 패드 교체",
            "content": "브레이크 패드 교체 시기는 어떻게 알 수 있나요?"
        },
        {
            "id": "battery_dead",
            "title": "배터리 방전",
            "content": "배터리가 방전되었을 때 대처법은 무엇인가요?"
        },
        {
            "id": "check_engine",
            "title": "체크 엔진 경고등",
            "content": "체크 엔진 경고등이 켜졌습니다. 어떻게 해야 하나요?"
        }
    ]
    
    return templates


@app.get("/events/{event_id}/status")
async def get_event_status(event_id: str):
    """이벤트 처리 상태 확인"""
    try:
        event_service_url = await get_service_url("event-gateway")
        if not event_service_url:
            raise HTTPException(status_code=503, detail="이벤트 게이트웨이 서비스를 찾을 수 없습니다")
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{event_service_url}/events/{event_id}/status")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"이벤트 ID {event_id}를 찾을 수 없습니다")
            else:
                raise HTTPException(status_code=response.status_code, detail="이벤트 상태 조회 중 오류가 발생했습니다")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"이벤트 상태 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"이벤트 상태 조회 중 오류 발생: {str(e)}")


@app.get("/supervisor/responses/{client_id}")
async def get_supervisor_response(client_id: str):
    """슈퍼바이저 응답 조회"""
    try:
        supervisor_url = await get_service_url("supervisor")
        if not supervisor_url:
            raise HTTPException(status_code=503, detail="슈퍼바이저 서비스를 찾을 수 없습니다")
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(f"{supervisor_url}/responses/{client_id}")
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                # 응답이 아직 없는 경우 빈 객체 반환
                return {}
            else:
                raise HTTPException(status_code=response.status_code, detail="슈퍼바이저 응답 조회 중 오류가 발생했습니다")
    except httpx.TimeoutException:
        logger.error(f"슈퍼바이저 응답 조회 시간 초과: client_id={client_id}")
        raise HTTPException(status_code=504, detail="슈퍼바이저 응답 조회 시간이 초과되었습니다")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"슈퍼바이저 응답 조회 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=f"슈퍼바이저 응답 조회 중 오류 발생: {str(e)}")


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
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
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
                "version": "1.1.0",
                "description": "API Gateway for A2A-MCP system"
            }
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
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
    pass 