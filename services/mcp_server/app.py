#!/usr/bin/env python3
"""
MCP(Model Context Protocol) 서버 서비스
에이전트가 다양한 도구(Tool)를 활용하여 목적에 맞는 업무를 수행할 수 있도록 돕는 인터페이스
Tool 레지스트리 관리, 도구 실행, 컨텍스트 관리, 취소 기능 제공
LLM 서비스와 통합된 향상된 버전
"""

import uuid
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Set
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx
import logging
import json
import asyncio

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("mcp_server")

# FastAPI 앱 생성
app = FastAPI(
    title="Model Context Protocol(MCP) 서버",
    description="에이전트가 목적에 맞는 Tool을 활용할 수 있게 하는 인터페이스, Tool 관리, 실행 및 모니터링",
    version="1.3.0"
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
TOOL_REGISTRY_URL = os.getenv("TOOL_REGISTRY_URL", "http://tool-registry:8005/tools")
LLM_REGISTRY_URL = os.getenv("LLM_REGISTRY_URL", "http://llm-registry:8101")

# 재시도 설정
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", "1.0"))
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "10.0"))

# 실행 중인 작업 저장소
active_executions: Dict[str, Dict[str, Any]] = {}

# 컨텍스트 캐시 - 에이전트별 상태 및 컨텍스트 저장
agent_contexts: Dict[str, Dict[str, Any]] = {}

# 도구 캐시
tool_cache: Dict[str, Dict[str, Any]] = {}
tool_cache_timestamp = 0
CACHE_TTL = 300  # 5분 캐시 유효시간

# 데이터 모델
class MCPRequest(BaseModel):
    """MCP 요청 모델"""
    tool_name: str
    parameters: Dict[str, Any]
    context: Dict[str, Any] = {}
    llm_config: Optional[Dict[str, Any]] = None
    agent_id: Optional[str] = None

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
    llm_service_id: Optional[str] = None
    llm_service_name: Optional[str] = None
    agent_id: Optional[str] = None

class ContextUpdateRequest(BaseModel):
    """컨텍스트 업데이트 요청 모델"""
    agent_id: str
    context_data: Dict[str, Any]
    append: bool = False

class ToolCategoryFilterParams(BaseModel):
    """도구 카테고리 필터 파라미터"""
    categories: Optional[List[str]] = None

class AgentToolRequest(BaseModel):
    """에이전트를 위한 도구 추천 요청"""
    agent_id: str
    capabilities: List[str] = []
    context: Optional[Dict[str, Any]] = None
    goal: Optional[str] = None

class LLMRequest(BaseModel):
    """LLM 요청 모델"""
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    messages: List[Dict[str, str]]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 1000
    context: Optional[Dict[str, Any]] = {}
    stream: bool = False

# HTTP 클라이언트
http_client = httpx.AsyncClient(timeout=60.0)

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "Model Context Protocol(MCP) 서버 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0",
        "executions_count": len(active_executions)
    }

@app.post("/execute")
async def execute_tool(request: ToolExecutionRequest, background_tasks: BackgroundTasks):
    """도구 실행 - 에이전트가 목적에 맞는 Tool을 활용하기 위한 주요 진입점"""
    # 실행 ID 생성
    execution_id = f"exec_{uuid.uuid4().hex[:8]}"
    
    # MCP 요청으로 변환
    mcp_request = MCPRequest(
        tool_name=request.tool_id,
        parameters=request.parameters,
        context={},
        llm_config={
            "service_id": request.llm_service_id,
            "service_name": request.llm_service_name
        } if (request.llm_service_id or request.llm_service_name) else None,
        agent_id=request.agent_id
    )
    
    # 실행 정보 저장
    active_executions[execution_id] = {
        "tool_name": mcp_request.tool_name,
        "parameters": mcp_request.parameters,
        "context": mcp_request.context,
        "llm_config": mcp_request.llm_config,
        "agent_id": mcp_request.agent_id,
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
        "error": execution.get("error"),
        "tool_name": execution["tool_name"],
        "agent_id": execution.get("agent_id"),
        "start_time": execution["start_time"],
        "end_time": execution.get("end_time")
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

@app.get("/tools")
async def get_all_tools(
    categories: Optional[List[str]] = Query(None, description="필터링할 도구 카테고리"),
    refresh: bool = Query(False, description="도구 캐시를 강제로 새로고침")
):
    """사용 가능한 모든 도구 목록 조회"""
    tools = await get_tools_from_registry(refresh=refresh)
    
    # 카테고리로 필터링
    if categories:
        filtered_tools = [tool for tool in tools if tool.get("category") in categories]
        return filtered_tools
    
    return tools

@app.get("/tools/{tool_id}")
async def get_tool_details(tool_id: str = Path(..., description="조회할 도구 ID")):
    """특정 도구의 상세 정보 조회"""
    tool_info = await get_tool_info(tool_id)
    
    if not tool_info:
        raise HTTPException(status_code=404, detail=f"도구를 찾을 수 없습니다: {tool_id}")
    
    return tool_info

@app.post("/tools/recommend")
async def recommend_tools_for_agent(request: AgentToolRequest):
    """에이전트의 목적, 능력, 컨텍스트에 맞는 도구 추천"""
    try:
        # 모든 도구 조회
        all_tools = await get_tools_from_registry()
        
        if not all_tools:
            return {"recommendations": [], "message": "사용 가능한 도구가 없습니다."}
            
        # 에이전트 컨텍스트 조회
        agent_context = agent_contexts.get(request.agent_id, {})
        if request.context:
            # 제공된 컨텍스트가 있으면 병합
            agent_context.update(request.context)
        
        # 추천 도구 목록
        recommended_tools = []
        
        # 능력 기반 필터링
        if request.capabilities:
            for tool in all_tools:
                tool_capabilities = tool.get("capabilities", [])
                # 에이전트 능력과 도구가 요구하는 능력이 일치하는지 확인
                if any(cap in request.capabilities for cap in tool_capabilities):
                    recommended_tools.append(tool)
        else:
            # 능력 정보가 없으면 모든 도구 추가
            recommended_tools = all_tools
        
        # 목적 기반 필터링 (LLM 사용 가능할 경우 향후 개선)
        if request.goal and len(recommended_tools) > 3:
            # 간단한 키워드 기반 필터링 (LLM 통합 전까지 사용)
            goal_keywords = request.goal.lower().split()
            scored_tools = []
            
            for tool in recommended_tools:
                score = 0
                tool_name = tool.get("name", "").lower()
                tool_desc = tool.get("description", "").lower()
                
                for keyword in goal_keywords:
                    if keyword in tool_name:
                        score += 3
                    if keyword in tool_desc:
                        score += 1
                
                if score > 0:
                    scored_tools.append((score, tool))
            
            # 점수 기준 상위 5개 도구 선택
            scored_tools.sort(reverse=True, key=lambda x: x[0])
            recommended_tools = [tool for _, tool in scored_tools[:5]]
        
        return {
            "agent_id": request.agent_id,
            "recommendations": recommended_tools,
            "capabilities_matched": request.capabilities,
            "goal": request.goal
        }
        
    except Exception as e:
        logger.error(f"도구 추천 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"도구 추천 오류: {str(e)}")

@app.post("/context/update")
async def update_agent_context(request: ContextUpdateRequest):
    """에이전트 컨텍스트 업데이트"""
    agent_id = request.agent_id
    
    if agent_id not in agent_contexts:
        agent_contexts[agent_id] = {}
    
    if request.append:
        # 기존 컨텍스트에 새 데이터 추가
        for key, value in request.context_data.items():
            if key in agent_contexts[agent_id]:
                # 리스트인 경우 항목 추가
                if isinstance(agent_contexts[agent_id][key], list) and isinstance(value, list):
                    agent_contexts[agent_id][key].extend(value)
                # 딕셔너리인 경우 병합
                elif isinstance(agent_contexts[agent_id][key], dict) and isinstance(value, dict):
                    agent_contexts[agent_id][key].update(value)
                # 그 외의 경우 덮어쓰기
                else:
                    agent_contexts[agent_id][key] = value
            else:
                agent_contexts[agent_id][key] = value
    else:
        # 컨텍스트 전체 교체
        agent_contexts[agent_id] = request.context_data
    
    return {
        "status": "success", 
        "message": f"에이전트 {agent_id}의 컨텍스트가 업데이트되었습니다.",
        "context_size": len(agent_contexts[agent_id])
    }

@app.get("/context/{agent_id}")
async def get_agent_context(agent_id: str):
    """에이전트 컨텍스트 조회"""
    if agent_id not in agent_contexts:
        return {"context": {}, "message": f"에이전트 {agent_id}의 컨텍스트가 없습니다."}
    
    return {"agent_id": agent_id, "context": agent_contexts[agent_id]}

@app.post("/llm/generate")
async def generate_with_llm(llm_request: LLMRequest):
    """LLM 서비스를 통한 텍스트 생성"""
    try:
        response = await http_client.post(
            f"{LLM_REGISTRY_URL}/generate",
            json=llm_request.dict()
        )
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LLM 서비스 오류: {response.text}"
            )
            
        return response.json()
    except Exception as e:
        logger.error(f"LLM 텍스트 생성 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"LLM 텍스트 생성 오류: {str(e)}")

@app.get("/llm/services")
async def list_llm_services():
    """사용 가능한 LLM 서비스 목록 조회"""
    try:
        response = await http_client.get(f"{LLM_REGISTRY_URL}/services")
        
        if response.status_code != 200:
            raise HTTPException(
                status_code=response.status_code,
                detail=f"LLM 서비스 목록 조회 오류: {response.text}"
            )
            
        return response.json()
    except Exception as e:
        logger.error(f"LLM 서비스 목록 조회 중 오류 발생: {str(e)}")
        raise HTTPException(status_code=500, detail=f"LLM 서비스 목록 조회 오류: {str(e)}")

@app.get("/executions")
async def list_executions(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10
):
    """실행 이력 조회"""
    filtered_executions = []
    
    for exec_id, execution in active_executions.items():
        # 필터 적용
        if agent_id and execution.get("agent_id") != agent_id:
            continue
        if status and execution.get("status") != status:
            continue
            
        filtered_executions.append({
            "execution_id": exec_id,
            "tool_name": execution["tool_name"],
            "agent_id": execution.get("agent_id"),
            "status": execution["status"],
            "start_time": execution["start_time"],
            "end_time": execution.get("end_time")
        })
    
    # 최신순 정렬
    filtered_executions.sort(key=lambda x: x["start_time"], reverse=True)
    
    # 제한 적용
    return filtered_executions[:limit]

# 백그라운드 작업
async def execute_tool_task(execution_id: str, request: MCPRequest):
    """도구 실행 작업"""
    try:
        # 도구 정보 조회
        tool_info = await get_tool_info(request.tool_name)
        
        if not tool_info:
            update_execution_status(execution_id, "failed", error=f"도구를 찾을 수 없습니다: {request.tool_name}")
            return
            
        # 에이전트 컨텍스트 정보 가져오기
        agent_context = {}
        if request.agent_id and request.agent_id in agent_contexts:
            agent_context = agent_contexts[request.agent_id]
            
        # 컨텍스트와 파라미터 병합
        context_and_params = {
            **request.parameters,
            "context": {**agent_context, **request.context}  # 컨텍스트 병합
        }
        
        # 도구 실행
        result = await execute_tool_by_type(tool_info, context_and_params, request.llm_config)
        
        # 에이전트 컨텍스트 업데이트 (필요한 경우)
        if request.agent_id and "context_updates" in result:
            if request.agent_id not in agent_contexts:
                agent_contexts[request.agent_id] = {}
                
            agent_contexts[request.agent_id].update(result["context_updates"])
            # 불필요한 데이터는 응답에서 제거
            del result["context_updates"]
        
        # 실행 결과 업데이트
        update_execution_status(execution_id, "completed", result=result)
        
    except Exception as e:
        logger.error(f"도구 실행 중 오류 발생: {str(e)}")
        update_execution_status(execution_id, "failed", error=str(e))

async def get_tools_from_registry(refresh: bool = False) -> List[Dict[str, Any]]:
    """도구 레지스트리에서 모든 도구 정보 가져오기 (캐싱 기능 포함)"""
    global tool_cache, tool_cache_timestamp
    
    current_time = time.time()
    
    # 캐시가 유효한지 확인
    if not refresh and tool_cache and current_time - tool_cache_timestamp < CACHE_TTL:
        return list(tool_cache.values())
    
    try:
        response = await http_client.get(TOOL_REGISTRY_URL)
        
        if response.status_code == 200:
            tools = response.json()
            
            # 캐시 업데이트
            tool_cache = {tool["tool_id"]: tool for tool in tools}
            tool_cache_timestamp = current_time
            
            return tools
        else:
            logger.error(f"도구 목록 조회 실패: {response.status_code} - {response.text}")
            # 캐시가 있으면 캐시된 데이터 반환
            if tool_cache:
                logger.warning("도구 레지스트리에서 데이터를 가져오지 못했습니다. 캐시된 데이터를 사용합니다.")
                return list(tool_cache.values())
            return []
                
    except Exception as e:
        logger.error(f"도구 목록 조회 중 오류 발생: {str(e)}")
        # 캐시가 있으면 캐시된 데이터 반환
        if tool_cache:
            logger.warning(f"도구 레지스트리에서 데이터를 가져오지 못했습니다. 캐시된 데이터를 사용합니다. 오류: {str(e)}")
            return list(tool_cache.values())
        return []

async def get_tool_info(tool_name: str) -> Optional[Dict[str, Any]]:
    """도구 정보 조회 (캐싱 활용)"""
    # 먼저 캐시에서 확인
    global tool_cache
    if tool_name in tool_cache:
        return tool_cache[tool_name]
    
    # 캐시에 없으면 API 호출
    try:
        response = await http_client.get(f"{TOOL_REGISTRY_URL}/{tool_name}")
        
        if response.status_code == 200:
            tool_info = response.json()
            # 캐시에 저장
            tool_cache[tool_name] = tool_info
            return tool_info
        else:
            logger.error(f"도구 정보 조회 실패: {response.status_code} - {response.text}")
            return None
                
    except Exception as e:
        logger.error(f"도구 정보 조회 중 오류 발생: {str(e)}")
        return None

async def execute_tool_by_type(
    tool_info: Dict[str, Any], 
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """도구 유형에 따른 실행 - 각 에이전트가 목적에 맞게 사용할 수 있는 Tool 실행 로직"""
    tool_type = tool_info.get("tool_type", "unknown")
    
    # LLM 지원이 필요한 도구인지 확인
    requires_llm = tool_info.get("requires_llm", False)
    
    # LLM 지원이 필요하지만 LLM 설정이 없는 경우
    if requires_llm and not llm_config:
        # 기본 LLM 서비스 사용
        llm_services = await list_llm_services()
        if llm_services:
            # 첫 번째 서비스 사용
            llm_config = {"service_id": llm_services[0].get("id")}
    
    # 각 에이전트의 목적에 맞는 Tool 실행
    if tool_type == "car_diagnostic":
        return await execute_car_diagnostic(parameters, llm_config)
    elif tool_type == "maintenance_scheduler":
        return await execute_maintenance_scheduler(parameters, llm_config)
    elif tool_type == "mechanic_finder":
        return await execute_mechanic_finder(parameters, llm_config)
    elif tool_type == "part_inventory":
        return await execute_part_inventory(parameters, llm_config)
    elif tool_type == "vehicle_manual":
        return await execute_vehicle_manual(parameters, llm_config)
    elif tool_type == "llm_assisted":
        return await execute_llm_assisted_tool(tool_info, parameters, llm_config)
    else:
        return {
            "error": f"지원하지 않는 도구 유형: {tool_type}",
            "tool_info": tool_info
        }

async def execute_car_diagnostic(
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """자동차 진단 도구 실행"""
    try:
        car_model = parameters.get("car_model")
        symptoms = parameters.get("symptoms", [])
        diagnostic_data = parameters.get("diagnostic_data", {})
        context = parameters.get("context", {})
        
        # 진단에 필요한 정보가 충분한지 확인
        if not car_model:
            return {"error": "차량 모델 정보가 필요합니다."}
            
        if not symptoms and not diagnostic_data:
            return {"error": "증상 또는 진단 데이터가 필요합니다."}
        
        # 실제 진단 수행 (LLM 활용 가능)
        issues = []
        
        # 간단한 예시 로직 (실제 구현에서는 더 복잡한 진단 로직 필요)
        # 증상 기반 진단
        if "엔진 소음" in symptoms:
            issues.append({
                "issue": "엔진 소음",
                "description": "엔진에서 비정상적인 소음이 발생하고 있습니다.",
                "severity": "중간",
                "possible_causes": ["엔진 오일 부족", "밸브 조정 필요", "벨트 마모"],
                "recommended_actions": ["엔진 오일 레벨 확인", "정비소 방문 점검 권장"]
            })
            
        if "시동 문제" in symptoms:
            issues.append({
                "issue": "시동 문제",
                "description": "차량 시동이 원활하게 걸리지 않습니다.",
                "severity": "높음",
                "possible_causes": ["배터리 방전", "시동모터 고장", "연료 공급 문제"],
                "recommended_actions": ["배터리 전압 확인", "연료량 확인", "정비소 방문 권장"]
            })
            
        # 진단 데이터 기반 진단
        if diagnostic_data:
            if diagnostic_data.get("battery_voltage", 12.5) < 11.5:
                issues.append({
                    "issue": "배터리 전압 낮음",
                    "description": "배터리 전압이 정상 범위 이하입니다.",
                    "severity": "높음",
                    "possible_causes": ["배터리 노후화", "발전기 고장", "전기 시스템 문제"],
                    "recommended_actions": ["배터리 충전 또는 교체", "발전기 점검"]
                })
                
            if diagnostic_data.get("engine_oil_life", 100) < 20:
                issues.append({
                    "issue": "엔진 오일 교체 필요",
                    "description": "엔진 오일 수명이 20% 이하로 감소했습니다.",
                    "severity": "중간",
                    "possible_causes": ["정기 유지보수 필요"],
                    "recommended_actions": ["엔진 오일 및 필터 교체"]
                })
        
        # 진단 결과가 없으면 LLM을 통한 추론 시도
        if not issues and llm_config:
            llm_response = await call_llm_service({
                "service_id": llm_config.get("service_id"),
                "messages": [
                    {"role": "system", "content": "당신은 자동차 진단 전문가입니다. 제공된 정보를 바탕으로 가능한 문제와 해결책을 제안하세요."},
                    {"role": "user", "content": f"차량: {car_model}, 증상: {', '.join(symptoms)}, 진단 데이터: {json.dumps(diagnostic_data, ensure_ascii=False)}"}
                ],
                "temperature": 0.3
            })
            
            if llm_response.get("content"):
                # LLM 응답을 구조화된 형식으로 변환 (간단한 예시)
                issues.append({
                    "issue": "LLM 기반 진단",
                    "description": llm_response.get("content"),
                    "severity": "미정",
                    "possible_causes": ["추가 진단 필요"],
                    "recommended_actions": ["전문가 상담 권장"]
                })
        
        # 컨텍스트 업데이트 정보
        context_updates = {
            "last_diagnostic_time": datetime.now().isoformat(),
            "car_model": car_model,
            "diagnosed_issues": [issue["issue"] for issue in issues]
        }
        
        return {
            "car_model": car_model,
            "issues_found": len(issues),
            "diagnostic_results": issues,
            "recommendation_summary": "발견된 문제점에 따른 조치를 취하세요.",
            "context_updates": context_updates  # 에이전트 컨텍스트 업데이트용
        }
        
    except Exception as e:
        logger.error(f"자동차 진단 도구 실행 중 오류 발생: {str(e)}")
        return {"error": f"자동차 진단 중 오류 발생: {str(e)}"}

async def execute_maintenance_scheduler(
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """정비 일정 도구 실행 (LLM 통합)"""
    maintenance_data = parameters.get("maintenance_data", {})
    
    # LLM을 사용한 정비 일정 개인화
    if llm_config:
        try:
            # 정비 데이터를 바탕으로 LLM 프롬프트 구성
            car_model = maintenance_data.get("car_model", "unknown")
            maintenance_type = maintenance_data.get("maintenance_type", "general")
            
            # 프롬프트 구성
            prompt = f"""
            당신은 자동차 정비 일정 관리 전문가입니다. 다음 정보를 바탕으로 최적의 정비 일정과 견적을 제공해주세요.
            
            차량 모델: {car_model}
            정비 유형: {maintenance_type}
            세부 정보: {json.dumps(maintenance_data, ensure_ascii=False)}
            
            다음 형식으로 응답해주세요:
            - 권장 정비 일정: (언제 정비를 받아야 하는지)
            - 예상 소요 시간: (시간 단위)
            - 예상 비용: (가격 범위)
            - 권장 정비소 유형: (일반 정비소, 제조사 공식 서비스 센터 등)
            - 추가 조언: (정비와 관련된 유용한 정보)
            """
            
            # LLM API 호출
            llm_response = await call_llm_service({
                "service_id": llm_config.get("service_id"),
                "service_name": llm_config.get("service_name"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            })
            
            # LLM 응답에서 필요한 정보 추출
            content = llm_response.get("content", "")
            
            # 간단한 정보 추출 (실제로는 더 정교한 파싱 필요)
            schedule = "가능한 빠른 시일 내"
            duration = "2 hours"
            cost = "₩150,000 ~ ₩200,000"
            shop_type = "일반 정비소"
            advice = ""
            
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith("- 권장 정비 일정:"):
                    schedule = line[10:].strip()
                elif line.startswith("- 예상 소요 시간:"):
                    duration = line[10:].strip()
                elif line.startswith("- 예상 비용:"):
                    cost = line[8:].strip()
                elif line.startswith("- 권장 정비소 유형:"):
                    shop_type = line[11:].strip()
                elif line.startswith("- 추가 조언:"):
                    advice = line[8:].strip()
            
            # 결과 구성
            return {
                "next_available_slot": schedule,
                "estimated_duration": duration,
                "estimated_cost": cost,
                "recommended_shop_type": shop_type,
                "additional_advice": advice,
                "llm_enhanced": True
            }
            
        except Exception as e:
            logger.error(f"LLM 정비 일정 생성 중 오류 발생: {str(e)}")
            # LLM 오류 시 기본 일정으로 폴백
            pass
    
    # 기본 일정 (LLM 없음 또는 오류 시)
    return {
        "next_available_slot": "2023-07-15T10:00:00",
        "estimated_duration": "2 hours",
        "estimated_cost": "₩150,000"
    }

async def execute_mechanic_finder(
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """정비사 찾기 도구 실행 - 근처 정비소 및 정비사 검색"""
    location_data = parameters.get("location", {})
    problem_type = parameters.get("problem_type", "general")
    
    # LLM을 사용한 정비사 추천
    if llm_config:
        try:
            # 위치 데이터를 기반으로 LLM 프롬프트 구성
            latitude = location_data.get("latitude", "unknown")
            longitude = location_data.get("longitude", "unknown")
            
            # 프롬프트 구성
            prompt = f"""
            당신은 자동차 정비사 추천 전문가입니다. 다음 정보를 바탕으로 적합한 정비소와 정비사를 추천해주세요.
            
            위치: 위도 {latitude}, 경도 {longitude}
            문제 유형: {problem_type}
            세부 정보: {json.dumps(parameters, ensure_ascii=False)}
            
            다음 형식으로 응답해주세요:
            - 추천 정비소: (3-5개 정비소 목록)
            - 각 정비소별 특화 분야
            - 예상 대기 시간
            - 거리
            - 연락처 정보
            """
            
            # LLM API 호출
            llm_response = await call_llm_service({
                "service_id": llm_config.get("service_id"),
                "service_name": llm_config.get("service_name"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            })
            
            # 응답 처리 및 결과 반환
            return {
                "content": llm_response.get("content", ""),
                "mechanics": [
                    {
                        "name": "정비소 정보를 찾을 수 없습니다",
                        "distance": "미상",
                        "specialty": "일반 정비",
                        "contact": "정보 없음"
                    }
                ],
                "llm_enhanced": True
            }
            
        except Exception as e:
            logger.error(f"정비사 찾기 중 오류 발생: {str(e)}")
            # 오류 시 기본 응답으로 폴백
    
    # 기본 응답
    return {
        "mechanics": [
            {
                "name": "가까운 정비소를 찾을 수 없습니다",
                "distance": "미상",
                "specialty": "일반 정비",
                "contact": "정보 없음"
            }
        ]
    }

async def execute_part_inventory(
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """부품 재고 관리 도구 - 필요한 부품 검색 및 재고 확인"""
    part_data = parameters.get("part", {})
    vehicle_model = parameters.get("vehicle_model", "unknown")
    
    # 기본 응답
    return {
        "parts": [
            {
                "name": part_data.get("name", "unknown"),
                "available": True,
                "price": "₩150,000",
                "estimated_arrival": "2023-07-15"
            }
        ]
    }

async def execute_vehicle_manual(
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """차량 매뉴얼 도구 - 차량 관련 문서 및 매뉴얼 검색"""
    query = parameters.get("query", "")
    vehicle_model = parameters.get("vehicle_model", "unknown")
    
    # LLM을 사용한 매뉴얼 검색
    if llm_config and query:
        try:
            # 프롬프트 구성
            prompt = f"""
            당신은 자동차 매뉴얼 전문가입니다. 다음 차량과 관련된 질문에 매뉴얼 정보를 바탕으로 답변해주세요.
            
            차량 모델: {vehicle_model}
            질문: {query}
            
            정확한 매뉴얼 정보와 함께 사용자가 쉽게 이해할 수 있는 설명을 제공해주세요.
            """
            
            # LLM API 호출
            llm_response = await call_llm_service({
                "service_id": llm_config.get("service_id"),
                "service_name": llm_config.get("service_name"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3
            })
            
            # 응답 처리 및 결과 반환
            return {
                "content": llm_response.get("content", ""),
                "manual_sections": ["관련 섹션을 찾을 수 없습니다."],
                "llm_enhanced": True
            }
            
        except Exception as e:
            logger.error(f"차량 매뉴얼 검색 중 오류 발생: {str(e)}")
            # 오류 시 기본 응답으로 폴백
    
    # 기본 응답
    return {
        "manual_sections": ["관련 섹션을 찾을 수 없습니다."],
        "content": "요청하신 정보를 찾을 수 없습니다."
    }

async def execute_llm_assisted_tool(
    tool_info: Dict[str, Any],
    parameters: Dict[str, Any],
    llm_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """LLM을 활용한 범용 도구 실행"""
    try:
        if not llm_config:
            return {"error": "LLM 설정이 필요합니다."}
            
        tool_name = tool_info.get("name", "알 수 없는 도구")
        tool_description = tool_info.get("description", "도구 설명 없음")
        tool_instructions = tool_info.get("instructions", "")
        
        # 파라미터에서 쿼리 추출
        query = parameters.get("query", "")
        context = parameters.get("context", {})
        
        if not query:
            return {"error": "쿼리 파라미터가 필요합니다."}
        
        # 도구 설명과 명령에 기반한 프롬프트 생성
        system_prompt = f"""당신은 '{tool_name}'이라는 도구를 담당하는 AI 전문가입니다.
도구 설명: {tool_description}
수행해야 할 작업: {tool_instructions}

사용자의 질문에 대해 이 도구를 사용하여 전문적인 답변을 제공하세요.
답변은 정확하고 유용해야 합니다.
"""

        # 컨텍스트 정보가 있으면 프롬프트에 추가
        if context:
            context_str = json.dumps(context, ensure_ascii=False)
            system_prompt += f"\n관련 컨텍스트 정보: {context_str}"
            
        # LLM 호출
        llm_response = await call_llm_service({
            "service_id": llm_config.get("service_id"),
            "service_name": llm_config.get("service_name"),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            "temperature": 0.4
        })
        
        # 응답 구성
        return {
            "tool_name": tool_name,
            "query": query,
            "response": llm_response.get("content", "응답을 생성할 수 없습니다."),
            "context_updates": {
                "last_tool_used": tool_name,
                "last_query": query,
                "last_response_time": datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        logger.error(f"LLM 도구 실행 중 오류 발생: {str(e)}")
        return {"error": f"LLM 도구 실행 오류: {str(e)}"}

async def call_llm_service(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 서비스 호출"""
    try:
        response = await http_client.post(
            f"{LLM_REGISTRY_URL}/generate",
            json=request_data
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"LLM 서비스 호출 실패: {response.status_code} - {response.text}")
            return {"error": f"LLM 서비스 호출 실패: {response.status_code}"}
            
    except Exception as e:
        logger.error(f"LLM 서비스 호출 중 오류 발생: {str(e)}")
        return {"error": f"LLM 서비스 호출 오류: {str(e)}"}

def update_execution_status(
    execution_id: str, 
    status: str, 
    result: Dict[str, Any] = None, 
    error: str = None
):
    """실행 상태 업데이트"""
    if execution_id in active_executions:
        execution = active_executions[execution_id]
        execution["status"] = status
        execution["end_time"] = datetime.now().isoformat()
        
        if result is not None:
            execution["result"] = result
            
        if error is not None:
            execution["error"] = error

# 서비스 등록 함수
async def register_service():
    """서비스 레지스트리에 MCP 서버 등록"""
    try:
        service_data = {
            "name": "mcp-server",
            "url": "http://mcp-server:8004",
            "health_check_url": "http://mcp-server:8004/health",
            "metadata": {
                "version": "1.3.0",
                "description": "Model Context Protocol 서버",
                "capabilities": ["tool_management", "context_management", "llm_integration"]
            }
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for retry in range(MAX_RETRIES):
                try:
                    response = await client.post(SERVICE_REGISTRY_URL, json=service_data)
                    if response.status_code == 200:
                        logger.info("MCP 서버가 서비스 레지스트리에 등록되었습니다.")
                        return
                    else:
                        logger.warning(f"서비스 레지스트리 등록 실패: {response.status_code}")
                        if retry < MAX_RETRIES - 1:
                            logger.info(f"서비스 레지스트리 등록 재시도 중 ({retry+1}/{MAX_RETRIES})")
                            await asyncio.sleep(RETRY_DELAY * (retry + 1))  # 지수 백오프
                except Exception as e:
                    logger.error(f"서비스 레지스트리 통신 오류 (시도 {retry+1}/{MAX_RETRIES}): {str(e)}")
                    if retry < MAX_RETRIES - 1:
                        logger.info(f"서비스 레지스트리 등록 재시도 중 ({retry+1}/{MAX_RETRIES})")
                        await asyncio.sleep(RETRY_DELAY * (retry + 1))
    except Exception as e:
        logger.error(f"서비스 레지스트리 등록 중 오류 발생: {str(e)}")
        # 등록 실패 시에도 서비스는 계속 동작

async def get_service_url(service_name: str) -> Optional[str]:
    """서비스 레지스트리에서 서비스 URL 조회"""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            for retry in range(MAX_RETRIES):
                try:
                    response = await client.get(f"{SERVICE_REGISTRY_URL}/discovery/{service_name}")
                    
                    if response.status_code == 200:
                        services = response.json()
                        if services and len(services) > 0:
                            # 첫 번째 서비스의 URL 사용
                            return services[0].get("url")
                    
                    # 서비스를 찾지 못하거나 오류 발생
                    if retry < MAX_RETRIES - 1:
                        logger.warning(f"서비스 '{service_name}' 조회 실패 (시도 {retry+1}/{MAX_RETRIES}): {response.status_code}")
                        await asyncio.sleep(RETRY_DELAY * (retry + 1))
                    else:
                        # 마지막 시도에서도 실패하면 폴백 URL 반환
                        logger.error(f"서비스 '{service_name}' 조회 실패, 폴백 URL 사용")
                        return get_fallback_url(service_name)
                except Exception as e:
                    logger.error(f"서비스 조회 중 오류 발생 (시도 {retry+1}/{MAX_RETRIES}): {str(e)}")
                    if retry < MAX_RETRIES - 1:
                        await asyncio.sleep(RETRY_DELAY * (retry + 1))
                    else:
                        return get_fallback_url(service_name)
    except Exception as e:
        logger.error(f"서비스 조회 처리 중 오류 발생: {str(e)}")
        return get_fallback_url(service_name)
    
    # 모든 시도 실패 시 폴백 URL 반환
    return get_fallback_url(service_name)

def get_fallback_url(service_name: str) -> Optional[str]:
    """폴백 URL 반환"""
    fallback_urls = {
        "tool-registry": "http://tool-registry:8005",
        "agent-card-registry": "http://agent-card-registry:8006",
        "llm-registry": "http://llm-registry:8101",
        "supervisor": "http://supervisor:8003"
    }
    
    return fallback_urls.get(service_name)

# 이벤트 핸들러
@app.on_event("startup")
async def startup_event():
    """시작 이벤트 핸들러"""
    # 서비스 레지스트리 등록 시도
    await register_service()
    
    # 도구 캐시 초기화
    await get_tools_from_registry(refresh=True)

@app.on_event("shutdown")
async def shutdown_event():
    """종료 이벤트 핸들러"""
    await http_client.aclose()

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8004, reload=True) 