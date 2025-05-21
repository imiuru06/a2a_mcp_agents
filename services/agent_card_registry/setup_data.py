#!/usr/bin/env python3
"""
Agent Card Registry 초기 데이터 설정 스크립트
자동차 정비 에이전트와 관련 기능을 설정합니다.
"""

import httpx
import asyncio
import json
from datetime import datetime

# 서비스 설정
AGENT_CARD_REGISTRY_URL = "http://157.173.113.114:48006"  # 로컬 개발 환경

# 자동차 정비 관련 기능
CAR_CAPABILITIES = [
    {
        "name": "car_troubleshooting",
        "description": "자동차 문제 진단 및 해결 방법 제공",
        "category": "automotive",
        "priority": 8,
        "metadata": {
            "requires_diagnostic_data": True,
            "provides_recommendations": True
        }
    },
    {
        "name": "engine_diagnostics",
        "description": "엔진 상태 진단 및 문제 분석",
        "category": "automotive",
        "priority": 9,
        "metadata": {
            "diagnostic_types": ["엔진 오일", "엔진 온도", "점화 시스템"]
        }
    },
    {
        "name": "car_maintenance",
        "description": "자동차 정비 및 유지보수 일정 관리",
        "category": "automotive",
        "priority": 7,
        "metadata": {
            "maintenance_types": ["정기 점검", "오일 교체", "필터 교체"]
        }
    },
    {
        "name": "service_scheduling",
        "description": "정비소 예약 및 일정 관리",
        "category": "service",
        "priority": 6,
        "metadata": {
            "provides_booking": True
        }
    },
    {
        "name": "car_diagnostics",
        "description": "전반적인 자동차 상태 진단",
        "category": "automotive",
        "priority": 8,
        "metadata": {
            "diagnostic_areas": ["엔진", "브레이크", "전기", "연료", "냉각"]
        }
    },
    {
        "name": "sensor_analysis",
        "description": "자동차 센서 데이터 분석",
        "category": "data_analysis",
        "priority": 7,
        "metadata": {
            "sensor_types": ["온도", "압력", "속도", "연료"]
        }
    },
    {
        "name": "general_assistance",
        "description": "일반적인 도움말 및 안내",
        "category": "general",
        "priority": 5,
        "metadata": {
            "general_purpose": True
        }
    },
    {
        "name": "warning_light_analysis",
        "description": "차량 경고등 분석 및 대응 방안 제시",
        "category": "automotive",
        "priority": 9,
        "metadata": {
            "warning_types": ["엔진 오일", "브레이크", "연료", "배터리", "냉각수", "타이어 압력"],
            "provides_emergency_guidance": True
        }
    },
    {
        "name": "mechanic_recommendation",
        "description": "사용자 위치 기반 적합한 정비소 추천",
        "category": "service",
        "priority": 7,
        "metadata": {
            "uses_location": True,
            "provides_reviews": True
        }
    },
    {
        "name": "part_ordering",
        "description": "차량 부품 검색 및 주문 지원",
        "category": "procurement",
        "priority": 6,
        "metadata": {
            "supports_pricing": True,
            "supports_delivery_tracking": True
        }
    },
    {
        "name": "maintenance_advice",
        "description": "차량 유지 관리 조언 및 팁 제공",
        "category": "advisory",
        "priority": 5,
        "metadata": {
            "advice_types": ["정기 점검", "계절별 관리", "장거리 운행", "연비 개선"]
        }
    }
]

# 자동차 정비 관련 에이전트
CAR_AGENTS = [
    {
        "name": "mechanic_agent",
        "description": "자동차 정비 전문 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["car_troubleshooting", "engine_diagnostics", "car_maintenance"],
        "metadata": {
            "specialty": "엔진 및 진단",
            "experience_level": "전문가",
            "languages": ["한국어", "영어"]
        }
    },
    {
        "name": "service_agent",
        "description": "정비 예약 전문 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["service_scheduling", "car_maintenance"],
        "metadata": {
            "specialty": "일정 관리",
            "experience_level": "중급",
            "languages": ["한국어"]
        }
    },
    {
        "name": "diagnostic_agent",
        "description": "차량 진단 전문 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["car_diagnostics", "sensor_analysis", "engine_diagnostics"],
        "metadata": {
            "specialty": "센서 데이터 분석",
            "experience_level": "전문가",
            "languages": ["한국어", "영어"]
        }
    },
    {
        "name": "general_agent",
        "description": "일반 안내 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["general_assistance"],
        "metadata": {
            "specialty": "일반 안내",
            "experience_level": "초급",
            "languages": ["한국어", "영어", "일본어"]
        }
    },
    {
        "name": "warning_light_expert",
        "description": "차량 경고등 전문 분석 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["warning_light_analysis", "car_troubleshooting", "car_diagnostics"],
        "metadata": {
            "specialty": "경고등 및 오류 코드 분석",
            "experience_level": "전문가",
            "languages": ["한국어", "영어"],
            "tool_integration": ["car_diagnostic_tool", "vehicle_manual_tool"]
        }
    },
    {
        "name": "master_mechanic",
        "description": "마스터 정비사 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["car_troubleshooting", "engine_diagnostics", "car_diagnostics", "warning_light_analysis", "maintenance_advice"],
        "metadata": {
            "specialty": "종합 진단 및 수리",
            "experience_level": "마스터",
            "languages": ["한국어", "영어"],
            "certifications": ["ASE 마스터 테크니션", "자동차 정비 기능장"],
            "tool_integration": ["car_diagnostic_tool", "vehicle_manual_tool", "part_inventory_tool"]
        }
    },
    {
        "name": "service_advisor",
        "description": "서비스 어드바이저 에이전트",
        "version": "1.0.0",
        "url": "http://sub-agent:8000/events",
        "health_check_url": "http://sub-agent:8000/health",
        "capabilities": ["service_scheduling", "mechanic_recommendation", "maintenance_advice", "part_ordering"],
        "metadata": {
            "specialty": "고객 상담 및 서비스 추천",
            "experience_level": "고급",
            "languages": ["한국어"],
            "tool_integration": ["maintenance_scheduler_tool", "mechanic_finder_tool"]
        }
    }
]

async def setup_capabilities():
    """Agent Card Registry에 기능 등록"""
    print("기능 등록 시작...")
    
    async with httpx.AsyncClient() as client:
        for capability in CAR_CAPABILITIES:
            try:
                response = await client.post(
                    f"{AGENT_CARD_REGISTRY_URL}/capabilities",
                    json=capability
                )
                
                if response.status_code in (200, 201):
                    print(f"기능 등록 성공: {capability['name']}")
                else:
                    print(f"기능 등록 실패: {capability['name']} - {response.status_code}")
                    print(f"응답: {response.text}")
            except Exception as e:
                print(f"기능 등록 중 오류 발생: {capability['name']} - {str(e)}")

async def setup_agents():
    """Agent Card Registry에 에이전트 등록"""
    print("에이전트 등록 시작...")
    
    async with httpx.AsyncClient() as client:
        for agent in CAR_AGENTS:
            try:
                response = await client.post(
                    f"{AGENT_CARD_REGISTRY_URL}/agents",
                    json=agent
                )
                
                if response.status_code in (200, 201):
                    print(f"에이전트 등록 성공: {agent['name']}")
                else:
                    print(f"에이전트 등록 실패: {agent['name']} - {response.status_code}")
                    print(f"응답: {response.text}")
            except Exception as e:
                print(f"에이전트 등록 중 오류 발생: {agent['name']} - {str(e)}")

async def main():
    """메인 실행 함수"""
    print("Agent Card Registry 데이터 설정 시작...")
    
    # 1. 기능 등록
    await setup_capabilities()
    
    # 2. 에이전트 등록
    await setup_agents()
    
    print("설정 완료!")

if __name__ == "__main__":
    asyncio.run(main()) 