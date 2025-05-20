#!/usr/bin/env python3
"""
MSA 구조의 MCP(Model Context Protocol) 서버 구현

MCP 서버는 다음 기능을 제공합니다:
- 도구 실행 프록시
- 컨텍스트 관리
- 취소 기능
- 병렬 실행 지원
"""

import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Union, Callable

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("mcp_server")

# ----- 데이터 모델 -----

class ToolParameter(BaseModel):
    """도구 파라미터 정의"""
    name: str
    type: str
    description: str
    required: bool = False
    default: Optional[Any] = None


class ToolDefinition(BaseModel):
    """MCP 도구 정의"""
    tool_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    version: str = "1.0"
    parameters: List[ToolParameter]
    return_schema: Dict[str, Any]
    container_image: Optional[str] = None
    is_stateful: bool = False
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ExecutionStatus(str, Enum):
    """실행 상태"""
    from enum import Enum
    
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ToolExecution(BaseModel):
    """도구 실행 정보"""
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_id: str
    tool_name: str
    parameters: Dict[str, Any]
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    context_id: Optional[str] = None


class ExecutionContext(BaseModel):
    """실행 컨텍스트"""
    context_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    state: Dict[str, Any] = Field(default_factory=dict)
    history: List[str] = Field(default_factory=list)  # 실행 ID 목록


# ----- 요청/응답 모델 -----

class ToolExecutionRequest(BaseModel):
    """도구 실행 요청"""
    parameters: Dict[str, Any]
    context_id: Optional[str] = None
    timeout_seconds: Optional[int] = None
    callback_url: Optional[str] = None


class ToolExecutionResponse(BaseModel):
    """도구 실행 응답"""
    execution_id: str
    status: str
    created_at: datetime
    message: str


class ToolRegistrationRequest(BaseModel):
    """도구 등록 요청"""
    name: str
    description: str
    version: str
    parameters: List[ToolParameter]
    return_schema: Dict[str, Any]
    container_image: Optional[str] = None
    is_stateful: bool = False


class ContextCreationRequest(BaseModel):
    """컨텍스트 생성 요청"""
    name: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    initial_state: Dict[str, Any] = Field(default_factory=dict)


# ----- 인메모리 저장소 (실제 구현에서는 데이터베이스 사용) -----

tools: Dict[str, ToolDefinition] = {}
executions: Dict[str, ToolExecution] = {}
contexts: Dict[str, ExecutionContext] = {}

# 일부 도구 구현 (실제로는 외부 컨테이너나 서비스를 호출)
tool_implementations: Dict[str, Callable] = {}


# ----- FastAPI 앱 생성 -----

app = FastAPI(
    title="MCP 서버",
    description="Model Context Protocol 도구 실행 서버",
    version="1.0.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 보안을 위해 실제 환경에서는 제한 필요
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----- 유틸리티 함수 -----

def validate_parameters(tool: ToolDefinition, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    도구 매개변수 검증
    
    Args:
        tool: 도구 정의
        parameters: 요청 매개변수
        
    Returns:
        검증된 매개변수
    """
    validated = {}
    
    # 필수 매개변수 확인
    for param in tool.parameters:
        if param.required and param.name not in parameters:
            raise ValueError(f"필수 매개변수 '{param.name}'이(가) 없습니다.")
        
        if param.name in parameters:
            # 타입 체크는 실제 구현에서 더 정교하게 수행
            validated[param.name] = parameters[param.name]
        elif param.default is not None:
            validated[param.name] = param.default
    
    return validated


async def execute_tool_task(execution_id: str):
    """
    백그라운드에서 도구 실행
    
    Args:
        execution_id: 실행 ID
    """
    if execution_id not in executions:
        logger.error(f"실행 ID를 찾을 수 없음: {execution_id}")
        return
    
    execution = executions[execution_id]
    tool_id = execution.tool_id
    
    if tool_id not in tools:
        execution.status = ExecutionStatus.FAILED
        execution.error_message = f"도구 ID를 찾을 수 없음: {tool_id}"
        return
    
    tool = tools[tool_id]
    
    # 상태 업데이트
    execution.status = ExecutionStatus.RUNNING
    execution.start_time = datetime.now()
    
    try:
        # 도구 구현 찾기 (실제로는 컨테이너나 외부 서비스 호출)
        if tool.name in tool_implementations:
            logger.info(f"도구 실행: {tool.name}, 실행 ID: {execution_id}")
            
            # 도구 실행
            result = await tool_implementations[tool.name](**execution.parameters)
            
            # 결과 업데이트
            execution.status = ExecutionStatus.COMPLETED
            execution.result = result
        else:
            # 실제 구현에서는 컨테이너나 외부 서비스 호출
            # 여기서는 간단한 모의 결과를 생성합니다
            await asyncio.sleep(2)  # 도구 실행 시간 시뮬레이션
            
            # 모의 결과
            execution.status = ExecutionStatus.COMPLETED
            execution.result = {
                "message": f"{tool.name} 실행 완료 (모의)",
                "timestamp": datetime.now().isoformat(),
                "parameters": execution.parameters
            }
    except Exception as e:
        logger.error(f"도구 실행 오류: {str(e)}")
        execution.status = ExecutionStatus.FAILED
        execution.error_message = str(e)
    finally:
        execution.end_time = datetime.now()
        
        # 컨텍스트 업데이트
        if execution.context_id and execution.context_id in contexts:
            context = contexts[execution.context_id]
            context.history.append(execution_id)
            context.updated_at = datetime.now()
            
            # 성공한 경우 컨텍스트 상태 업데이트
            if execution.status == ExecutionStatus.COMPLETED and execution.result:
                # 상태 업데이트 로직 (도구마다 다를 수 있음)
                # 여기서는 단순히 결과를 상태에 추가
                context.state[f"last_{tool.name}_result"] = execution.result
        
        logger.info(f"도구 실행 완료: {tool.name}, 상태: {execution.status}")


# ----- API 엔드포인트 -----

@app.get("/")
async def root():
    """서버 상태 확인"""
    return {"status": "active", "version": "1.0.0"}


# 도구 관리 API

@app.post("/api/v1/tools", status_code=status.HTTP_201_CREATED)
async def register_tool(request: ToolRegistrationRequest):
    """새 도구 등록"""
    tool_id = str(uuid.uuid4())
    
    tool = ToolDefinition(
        tool_id=tool_id,
        name=request.name,
        description=request.description,
        version=request.version,
        parameters=request.parameters,
        return_schema=request.return_schema,
        container_image=request.container_image,
        is_stateful=request.is_stateful
    )
    
    tools[tool_id] = tool
    logger.info(f"도구 등록: {request.name} (ID: {tool_id})")
    
    return {
        "tool_id": tool_id,
        "name": request.name,
        "message": "도구가 성공적으로 등록되었습니다."
    }


@app.get("/api/v1/tools")
async def list_tools():
    """등록된 모든 도구 목록"""
    return [tool.dict() for tool in tools.values()]


@app.get("/api/v1/tools/{tool_id}")
async def get_tool(tool_id: str):
    """도구 정보 조회"""
    if tool_id not in tools:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다.")
    
    return tools[tool_id].dict()


@app.get("/api/v1/tools/search")
async def search_tools(q: Optional[str] = None):
    """도구 검색"""
    if not q:
        return [tool.dict() for tool in tools.values()]
    
    # 간단한 검색 구현
    results = []
    q = q.lower()
    
    for tool in tools.values():
        if (q in tool.name.lower() or 
            q in tool.description.lower()):
            results.append(tool.dict())
    
    return results


# 도구 실행 API

@app.post("/api/v1/tools/{tool_name}/execute", response_model=ToolExecutionResponse)
async def execute_tool(
    tool_name: str,
    request: ToolExecutionRequest,
    background_tasks: BackgroundTasks
):
    """도구 실행 요청"""
    # 도구 찾기
    tool = None
    tool_id = None
    
    for t_id, t in tools.items():
        if t.name == tool_name:
            tool = t
            tool_id = t_id
            break
    
    if not tool:
        raise HTTPException(status_code=404, detail=f"도구 '{tool_name}'을(를) 찾을 수 없습니다.")
    
    try:
        # 매개변수 검증
        validated_params = validate_parameters(tool, request.parameters)
        
        # 실행 객체 생성
        execution_id = str(uuid.uuid4())
        execution = ToolExecution(
            execution_id=execution_id,
            tool_id=tool_id,
            tool_name=tool_name,
            parameters=validated_params,
            context_id=request.context_id
        )
        
        executions[execution_id] = execution
        
        # 백그라운드에서 실행
        background_tasks.add_task(execute_tool_task, execution_id)
        
        return ToolExecutionResponse(
            execution_id=execution_id,
            status="pending",
            created_at=execution.created_at,
            message="도구 실행이 시작되었습니다."
        )
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"도구 실행 요청 처리 중 오류: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/executions/{execution_id}")
async def get_execution_status(execution_id: str):
    """실행 상태 조회"""
    if execution_id not in executions:
        raise HTTPException(status_code=404, detail="실행 ID를 찾을 수 없습니다.")
    
    return executions[execution_id].dict()


@app.post("/api/v1/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    """실행 취소 요청"""
    if execution_id not in executions:
        raise HTTPException(status_code=404, detail="실행 ID를 찾을 수 없습니다.")
    
    execution = executions[execution_id]
    
    if execution.status not in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]:
        return {
            "execution_id": execution_id,
            "status": execution.status,
            "message": f"이미 {execution.status} 상태인 실행은 취소할 수 없습니다."
        }
    
    # 실행 취소 처리
    execution.status = ExecutionStatus.CANCELLED
    execution.end_time = datetime.now()
    
    return {
        "execution_id": execution_id,
        "status": "cancelled",
        "message": "실행이 취소되었습니다."
    }


# 컨텍스트 관리 API

@app.post("/api/v1/contexts", status_code=status.HTTP_201_CREATED)
async def create_context(request: ContextCreationRequest):
    """새 실행 컨텍스트 생성"""
    context_id = str(uuid.uuid4())
    
    context = ExecutionContext(
        context_id=context_id,
        name=request.name,
        metadata=request.metadata,
        state=request.initial_state
    )
    
    contexts[context_id] = context
    
    return {
        "context_id": context_id,
        "name": request.name,
        "message": "컨텍스트가 성공적으로 생성되었습니다."
    }


@app.get("/api/v1/contexts/{context_id}")
async def get_context(context_id: str):
    """컨텍스트 정보 조회"""
    if context_id not in contexts:
        raise HTTPException(status_code=404, detail="컨텍스트 ID를 찾을 수 없습니다.")
    
    return contexts[context_id].dict()


@app.put("/api/v1/contexts/{context_id}/state")
async def update_context_state(context_id: str, state: Dict[str, Any]):
    """컨텍스트 상태 업데이트"""
    if context_id not in contexts:
        raise HTTPException(status_code=404, detail="컨텍스트 ID를 찾을 수 없습니다.")
    
    # 상태 업데이트
    contexts[context_id].state.update(state)
    contexts[context_id].updated_at = datetime.now()
    
    return {
        "context_id": context_id,
        "message": "컨텍스트 상태가 업데이트되었습니다."
    }


@app.get("/api/v1/contexts/{context_id}/history")
async def get_context_history(context_id: str):
    """컨텍스트 실행 기록 조회"""
    if context_id not in contexts:
        raise HTTPException(status_code=404, detail="컨텍스트 ID를 찾을 수 없습니다.")
    
    context = contexts[context_id]
    history = []
    
    for execution_id in context.history:
        if execution_id in executions:
            history.append(executions[execution_id].dict())
    
    return history


# ----- 샘플 도구 구현 등록 -----

async def sample_weather_tool(location: str, units: str = "metric") -> Dict[str, Any]:
    """샘플 날씨 도구"""
    # 실제로는 외부 API 호출
    await asyncio.sleep(1)
    
    return {
        "location": location,
        "temperature": 22.5 if units == "metric" else 72.5,
        "units": units,
        "conditions": "맑음",
        "timestamp": datetime.now().isoformat()
    }


async def sample_car_diagnostic_tool(vehicle_id: str) -> Dict[str, Any]:
    """샘플 자동차 진단 도구"""
    # 실제로는 자동차 진단 시스템 연동
    await asyncio.sleep(1.5)
    
    return {
        "vehicle_id": vehicle_id,
        "error_codes": ["P0300", "P0171"],
        "descriptions": {
            "P0300": "랜덤/다중 실린더 실화 감지됨",
            "P0171": "연료 시스템 너무 희박 (뱅크 1)"
        },
        "severity": "중간",
        "timestamp": datetime.now().isoformat()
    }


@app.on_event("startup")
async def startup_event():
    """서버 시작 시 샘플 도구 등록"""
    logger.info("MCP 서버 시작 중...")
    
    # 샘플 도구 구현 등록
    tool_implementations["weather"] = sample_weather_tool
    tool_implementations["car_diagnostic"] = sample_car_diagnostic_tool
    
    # 샘플 도구 정의 등록
    weather_tool = ToolDefinition(
        name="weather",
        description="지정된 위치의 현재 날씨 정보 조회",
        parameters=[
            ToolParameter(name="location", type="string", description="도시 또는 위치", required=True),
            ToolParameter(name="units", type="string", description="미터법(metric) 또는 야드파운드법(imperial)", required=False, default="metric")
        ],
        return_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "temperature": {"type": "number"},
                "units": {"type": "string"},
                "conditions": {"type": "string"},
                "timestamp": {"type": "string"}
            }
        }
    )
    
    car_diagnostic_tool = ToolDefinition(
        name="car_diagnostic",
        description="자동차 진단 스캐너를 사용하여 오류 코드 조회",
        parameters=[
            ToolParameter(name="vehicle_id", type="string", description="차량 ID 또는 VIN", required=True)
        ],
        return_schema={
            "type": "object",
            "properties": {
                "vehicle_id": {"type": "string"},
                "error_codes": {"type": "array", "items": {"type": "string"}},
                "descriptions": {"type": "object"},
                "severity": {"type": "string"},
                "timestamp": {"type": "string"}
            }
        }
    )
    
    tools[weather_tool.tool_id] = weather_tool
    tools[car_diagnostic_tool.tool_id] = car_diagnostic_tool
    
    logger.info(f"샘플 도구 등록 완료: {len(tools)} 도구 활성화")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True) 