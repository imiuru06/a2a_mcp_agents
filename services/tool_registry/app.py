#!/usr/bin/env python3
"""
도구 레지스트리 서비스 - 도구 메타데이터 및 이미지 관리
에이전트가 활용할 수 있는 다양한 자동차 정비 관련 도구 제공
"""

from typing import Dict, List, Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# FastAPI 앱 생성
app = FastAPI(
    title="도구 레지스트리 서비스",
    description="에이전트가 활용할 수 있는 다양한 도구 메타데이터 및 이미지 관리",
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

# 도구 저장소
tools_registry: Dict[str, Dict[str, Any]] = {
    "car_diagnostic_tool": {
        "tool_id": "car_diagnostic_tool",
        "tool_type": "car_diagnostic",
        "name": "자동차 진단 도구",
        "description": "자동차 상태를 진단하고 문제를 식별하는 도구",
        "version": "1.0.0",
        "parameters": {
            "diagnostic_data": {
                "type": "object",
                "description": "진단에 필요한 데이터"
            }
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "issues": {"type": "array"},
                "recommendations": {"type": "array"}
            }
        }
    },
    "maintenance_scheduler_tool": {
        "tool_id": "maintenance_scheduler_tool",
        "tool_type": "maintenance_scheduler",
        "name": "정비 일정 관리 도구",
        "description": "자동차 정비 일정을 관리하는 도구",
        "version": "1.0.0",
        "parameters": {
            "maintenance_data": {
                "type": "object",
                "description": "정비 일정 관리에 필요한 데이터"
            }
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "next_available_slot": {"type": "string"},
                "estimated_duration": {"type": "string"},
                "estimated_cost": {"type": "string"}
            }
        }
    },
    "mechanic_finder_tool": {
        "tool_id": "mechanic_finder_tool",
        "tool_type": "mechanic_finder",
        "name": "정비사 찾기 도구",
        "description": "사용자 위치 기반으로 근처 정비소와 정비사를 찾는 도구",
        "version": "1.0.0",
        "parameters": {
            "location": {
                "type": "object",
                "description": "사용자의 현재 위치 정보",
                "properties": {
                    "latitude": {"type": "number"},
                    "longitude": {"type": "number"}
                }
            },
            "problem_type": {
                "type": "string",
                "description": "차량 문제 유형 (예: '엔진', '브레이크', '오일')"
            }
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "mechanics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "distance": {"type": "string"},
                            "specialty": {"type": "string"},
                            "contact": {"type": "string"}
                        }
                    }
                }
            }
        }
    },
    "part_inventory_tool": {
        "tool_id": "part_inventory_tool",
        "tool_type": "part_inventory",
        "name": "부품 재고 관리 도구",
        "description": "자동차 부품의 재고를 확인하고 주문하는 도구",
        "version": "1.0.0",
        "parameters": {
            "part": {
                "type": "object",
                "description": "부품 정보",
                "properties": {
                    "name": {"type": "string"},
                    "part_number": {"type": "string"},
                    "vehicle_model": {"type": "string"}
                }
            },
            "vehicle_model": {
                "type": "string",
                "description": "차량 모델 정보"
            }
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "parts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "available": {"type": "boolean"},
                            "price": {"type": "string"},
                            "estimated_arrival": {"type": "string"}
                        }
                    }
                }
            }
        }
    },
    "vehicle_manual_tool": {
        "tool_id": "vehicle_manual_tool",
        "tool_type": "vehicle_manual",
        "name": "차량 매뉴얼 도구",
        "description": "차량 매뉴얼 및 정비 가이드를 검색하고 제공하는 도구",
        "version": "1.0.0",
        "parameters": {
            "query": {
                "type": "string",
                "description": "사용자의 검색 쿼리"
            },
            "vehicle_model": {
                "type": "string",
                "description": "차량 모델 정보"
            }
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "manual_sections": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "content": {"type": "string"}
            }
        }
    }
}

# 데이터 모델
class Tool(BaseModel):
    """도구 모델"""
    tool_id: str
    tool_type: str
    name: str
    description: str
    version: str
    parameters: Dict[str, Any]
    output_schema: Dict[str, Any]

# API 엔드포인트
@app.get("/")
async def root():
    """서비스 루트 엔드포인트"""
    return {"message": "도구 레지스트리 서비스 API"}

@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {"status": "healthy"}

@app.get("/tools")
async def list_tools():
    """모든 도구 목록 조회"""
    return list(tools_registry.values())

@app.get("/tools/{tool_id}")
async def get_tool(tool_id: str):
    """특정 도구 정보 조회"""
    if tool_id not in tools_registry:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다.")
    
    return tools_registry[tool_id]

@app.post("/tools")
async def register_tool(tool: Tool):
    """새로운 도구 등록"""
    if tool.tool_id in tools_registry:
        raise HTTPException(status_code=400, detail="이미 등록된 도구 ID입니다.")
    
    tools_registry[tool.tool_id] = tool.dict()
    return {"status": "registered", "tool_id": tool.tool_id}

@app.put("/tools/{tool_id}")
async def update_tool(tool_id: str, tool: Tool):
    """도구 정보 업데이트"""
    if tool_id != tool.tool_id:
        raise HTTPException(status_code=400, detail="경로의 도구 ID와 요청 본문의 도구 ID가 일치하지 않습니다.")
    
    if tool_id not in tools_registry:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다.")
    
    tools_registry[tool_id] = tool.dict()
    return {"status": "updated", "tool_id": tool_id}

@app.delete("/tools/{tool_id}")
async def delete_tool(tool_id: str):
    """도구 삭제"""
    if tool_id not in tools_registry:
        raise HTTPException(status_code=404, detail="도구를 찾을 수 없습니다.")
    
    del tools_registry[tool_id]
    return {"status": "deleted", "tool_id": tool_id}

# 서버 실행
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8005, reload=True) 