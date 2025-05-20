#!/usr/bin/env python3
"""
A2A와 MCP 프로토콜 통합 예제

A2A와 MCP는 상호 보완적인 프로토콜로, 함께 사용하면 더 강력한 AI 시스템을 구축할 수 있습니다.
- A2A: 에이전트 간 협업 표준화 (수평적 오케스트레이션)
- MCP: 에이전트와 도구/리소스 간 통합 표준화 (수직적 통합)

참고: https://codingespresso.tistory.com/entry/Agent2AgentA2A%EC%99%80-MCP-%EC%99%84%EB%B2%BD-%EB%B9%84%EA%B5%90-%EB%B6%84%EC%84%9D
"""

import asyncio
import json
import logging
from typing import Dict, List, Any

# protocol_architecture.py에서 정의된 클래스와 함수 가져오기
from protocol_architecture import (
    AgentCard, A2AAgent, MCPRegistry, MCPTool, MCPDataSource,
    InteractionModality, TaskStatus
)

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("integration")

# --------------- 통합 시나리오: 자동차 정비소 ---------------

async def auto_repair_shop_scenario():
    """
    자동차 정비소 시나리오를 통한 A2A와 MCP 통합 예제
    
    시나리오 개요:
    1. 고객이 Shop Manager 에이전트에게 차량 문제를 보고 (A2A)
    2. Shop Manager가 문제를 진단하고 Mechanic 에이전트에게 작업 할당 (A2A)
    3. Mechanic이 차량 진단 도구를 사용하여 문제 확인 (MCP)
    4. Mechanic이 Parts Supplier 에이전트에게 필요한 부품 요청 (A2A)
    5. 모든 에이전트가 협력하여 수리 완료 (A2A + MCP)
    """
    logger.info("=== 자동차 정비소 시나리오 시작 ===")
    
    # 1. 에이전트 및 도구 생성
    shop_manager = create_shop_manager_agent()
    mechanic = create_mechanic_agent_with_tools()
    parts_supplier = create_parts_supplier_agent()
    
    # 2. 고객 요청 시뮬레이션 (A2A 작업 생성)
    logger.info("1. 고객이 Shop Manager에게 차량 문제 보고")
    task_id = shop_manager.create_task(
        title="차에서 소음 발생",
        description="차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.",
        context={
            "customer_id": "customer_123",
            "vehicle_id": "VIN_XYZ123",
            "vehicle_info": {
                "make": "현대",
                "model": "소나타",
                "year": 2018
            },
            "symptoms": ["엔진 소음", "경고등 점등"]
        }
    )
    logger.info(f"   - 작업 생성: {task_id}")
    
    # 3. Shop Manager가 문제 진단 (A2A 내부 처리)
    logger.info("2. Shop Manager가 문제 진단 수행")
    diagnosis_result = await diagnose_issue(shop_manager, task_id)
    logger.info(f"   - 진단 결과: {diagnosis_result.get('diagnosis', '진단 실패')}")
    
    # 4. Shop Manager가 Mechanic에게 작업 할당 (A2A 협업)
    logger.info("3. Shop Manager가 Mechanic에게 작업 할당")
    shop_manager.assign_task(task_id, mechanic.agent_card.agent_id)
    shop_manager.communicate(
        to_agent_id=mechanic.agent_card.agent_id,
        task_id=task_id,
        message=f"다음 차량의 진단과 수리를 요청합니다: {diagnosis_result.get('diagnosis', '증상 분석 필요')}"
    )
    
    # 5. 작업 전달 (실제로는 A2A 서버가 처리, 여기서는 로컬 시뮬레이션)
    mechanic.tasks[task_id] = shop_manager.tasks[task_id]
    mechanic.update_task_history(task_id, "작업을 수락했습니다. 진단을 시작합니다.")
    
    # 6. Mechanic이 MCP 도구를 사용하여 진단 (MCP 도구 활용)
    logger.info("4. Mechanic이 MCP 도구를 사용하여 차량 진단")
    
    # 6.1. 차량 스캔 도구 사용
    vehicle_id = mechanic.tasks[task_id].context.get("vehicle_id", "unknown")
    scan_result = mechanic.call_mcp_tool("scan_vehicle", vehicle_id=vehicle_id)
    
    if scan_result["status"] == "success":
        error_codes = scan_result["result"]["error_codes"]
        logger.info(f"   - 발견된 오류 코드: {', '.join(error_codes)}")
        mechanic.update_task_history(task_id, f"차량 스캔 결과: 오류 코드 {', '.join(error_codes)}")
        
        # 6.2. 수리 매뉴얼 도구 사용
        if error_codes:
            vehicle_info = mechanic.tasks[task_id].context.get("vehicle_info", {})
            repair_result = mechanic.call_mcp_tool(
                "repair_manual",
                query="procedure",
                error_code=error_codes[0],
                vehicle_make=vehicle_info.get("make", "Generic"),
                vehicle_model=vehicle_info.get("model", "Car")
            )
            
            if repair_result["status"] == "success":
                procedure = repair_result["result"].get("procedure", [])
                procedure_text = "\n".join([f"- {step}" for step in procedure])
                logger.info(f"   - 수리 절차 확인: {len(procedure)} 단계")
                mechanic.update_task_history(task_id, f"수리 절차:\n{procedure_text}")
    
    # 7. 부품이 필요한 경우 Parts Supplier에게 요청 (A2A 협업)
    logger.info("5. Mechanic이 Parts Supplier에게 부품 요청")
    parts_task_id = mechanic.create_task(
        title="부품 주문 요청",
        description="차량 수리에 필요한 부품 주문",
        context={"parent_task_id": task_id}
    )
    
    # Parts Supplier에게 작업 할당 (실제로는 A2A 서버를 통해)
    parts_supplier.tasks[parts_task_id] = mechanic.tasks[parts_task_id]
    
    # A2A 통신으로 Parts Supplier에게 부품 요청
    mechanic.communicate(
        to_agent_id=parts_supplier.agent_card.agent_id,
        task_id=parts_task_id,
        message="스파크 플러그(부품 #12345) 4개가 필요합니다."
    )
    
    # 8. Parts Supplier가 부품 요청 처리 (A2A 내부 처리)
    logger.info("6. Parts Supplier가 부품 요청 처리")
    parts_supplier.update_task_history(parts_task_id, "부품 요청을 확인했습니다.")
    
    # 부품 재고 확인 및 주문 처리
    order_result = await process_part_order(parts_supplier, parts_task_id, "12345", 4)
    
    if order_result["status"] == "success":
        order_details = (
            f"부품: {order_result['part_name']}, "
            f"수량: {order_result['quantity']}개, "
            f"금액: {order_result['total_price']}원"
        )
        logger.info(f"   - 주문 완료: {order_details}")
        
        # Mechanic에게 주문 결과 알림 (A2A 통신)
        parts_supplier.communicate(
            to_agent_id=mechanic.agent_card.agent_id,
            task_id=parts_task_id,
            message=f"부품 주문이 완료되었습니다. {order_details}"
        )
        
        # 실제로는 A2A 서버를 통해 에이전트 간 메시지가 교환됨
        mechanic.update_task_history(parts_task_id, f"부품 주문 확인: {order_details}")
    
    # 9. Mechanic이 수리 완료 (MCP + A2A 통합)
    logger.info("7. Mechanic이 수리 작업 완료")
    
    # 수리 완료 메시지 작성
    repair_summary = (
        "1. 차량 진단 스캐너로 오류 코드 확인\n"
        "2. 수리 매뉴얼에 따라 부품 교체 및 수리 절차 수행\n"
        "3. 주문한 스파크 플러그 설치\n"
        "4. 테스트 주행으로 문제 해결 확인"
    )
    
    # 작업 상태 업데이트
    mechanic.update_task_status(task_id, TaskStatus.COMPLETED)
    mechanic.update_task_history(task_id, f"수리 완료 내역:\n{repair_summary}")
    
    # Shop Manager에게 완료 보고 (A2A 통신)
    mechanic.communicate(
        to_agent_id=shop_manager.agent_card.agent_id,
        task_id=task_id,
        message="차량 수리가 완료되었습니다."
    )
    
    # 10. Shop Manager가 고객에게 결과 보고 (최종 A2A 처리)
    logger.info("8. Shop Manager가 고객에게 결과 보고")
    
    # 실제로는 A2A 서버를 통해 메시지가 전달됨
    shop_manager.tasks[task_id] = mechanic.tasks[task_id]
    shop_manager.update_task_history(
        task_id, 
        "고객님, 차량 수리가 완료되었습니다. 내원하시면 상세 설명 드리겠습니다."
    )
    
    # 11. 결과 요약
    logger.info("=== 시나리오 완료 ===")
    logger.info("각 에이전트가 맡은 역할:")
    logger.info("- Shop Manager: 고객 응대 및 작업 조정 (A2A 중심)")
    logger.info("- Mechanic: 차량 진단 및 수리 (A2A + MCP 통합)")
    logger.info("- Parts Supplier: 부품 재고 관리 및 주문 처리 (A2A 중심)")
    
    # 작업 기록 출력
    task_history = mechanic.get_task(task_id).get("history", [])
    logger.info("\n작업 기록:")
    for entry in task_history:
        logger.info(f"[{entry['agent_id']}] {entry['message']}")
    
    return {
        "task_id": task_id,
        "status": "completed",
        "message": "자동차 정비 시나리오가 성공적으로 완료되었습니다."
    }


# --------------- 에이전트 생성 함수 ---------------

def create_shop_manager_agent() -> A2AAgent:
    """Shop Manager 에이전트 생성"""
    shop_manager_card = AgentCard(
        agent_id="shop_manager_001",
        name="Shop Manager",
        description="자동차 수리점을 관리하고 고객과 소통하는 에이전트",
        version="1.0",
        skills=["customer_service", "task_delegation", "problem_diagnosis"],
        supported_modalities=[InteractionModality.TEXT],
        organization="Auto Repair Shop"
    )
    
    return A2AAgent(shop_manager_card)


def create_mechanic_agent_with_tools() -> A2AAgent:
    """Mechanic 에이전트 생성 (MCP 도구 포함)"""
    mechanic_card = AgentCard(
        agent_id="mechanic_001",
        name="Auto Mechanic",
        description="자동차 진단 및 수리를 수행하는 정비사 에이전트",
        version="1.0",
        skills=["car_diagnosis", "car_repair", "parts_replacement"],
        supported_modalities=[InteractionModality.TEXT, InteractionModality.IMAGE],
        organization="Auto Repair Shop"
    )
    
    # MCP 레지스트리 및 도구 생성
    mcp_registry = MCPRegistry()
    
    # 진단 스캐너 도구
    def scan_vehicle_impl(vehicle_id: str) -> Dict[str, Any]:
        return {
            "error_codes": ["P0300", "P0171"],
            "descriptions": {
                "P0300": "Random/Multiple Cylinder Misfire Detected",
                "P0171": "System Too Lean (Bank 1)"
            }
        }
    
    scanner_tool = MCPTool(
        name="scan_vehicle",
        description="차량 진단 스캐너를 사용하여 오류 코드 조회",
        parameters={
            "type": "object",
            "properties": {
                "vehicle_id": {"type": "string"}
            },
            "required": ["vehicle_id"]
        },
        return_schema={},
        implementation=scan_vehicle_impl
    )
    
    mcp_registry.register_resource(scanner_tool)
    
    # 수리 매뉴얼 데이터 소스
    repair_procedures = {
        "P0300": [
            "점화 플러그 검사 및 교체",
            "점화 코일 검사",
            "연료 인젝터 검사",
            "압축 테스트 수행"
        ],
        "P0171": [
            "공기 필터 검사",
            "MAF 센서 세척",
            "연료 압력 테스트",
            "산소 센서 검사"
        ]
    }
    
    def get_repair_procedure_impl(query: str, error_code: str, vehicle_make: str = "", vehicle_model: str = "") -> Dict[str, Any]:
        if error_code in repair_procedures:
            return {
                "error_code": error_code,
                "vehicle": f"{vehicle_make} {vehicle_model}",
                "procedure": repair_procedures[error_code]
            }
        return {"error": "Procedure not found"}
    
    repair_manual = MCPDataSource(
        name="repair_manual",
        description="수리 매뉴얼 데이터베이스에서 오류 코드별 수리 절차 조회",
        schema={},
        query_implementation=get_repair_procedure_impl
    )
    
    mcp_registry.register_resource(repair_manual)
    
    return A2AAgent(mechanic_card, mcp_registry)


def create_parts_supplier_agent() -> A2AAgent:
    """Parts Supplier 에이전트 생성"""
    supplier_card = AgentCard(
        agent_id="parts_supplier_001",
        name="Parts Supplier",
        description="자동차 부품을 공급하는 에이전트",
        version="1.0",
        skills=["parts_inventory", "pricing", "ordering"],
        supported_modalities=[InteractionModality.TEXT],
        organization="Auto Parts Inc."
    )
    
    return A2AAgent(supplier_card)


# --------------- 헬퍼 함수 ---------------

async def diagnose_issue(manager: A2AAgent, task_id: str) -> Dict[str, Any]:
    """Shop Manager가 문제 진단을 수행"""
    if task_id not in manager.tasks:
        return {"status": "error", "message": "Task not found"}
    
    # 증상 분석
    symptoms = manager.tasks[task_id].context.get("symptoms", [])
    diagnosis = f"증상 분석: {', '.join(symptoms)}"
    
    # 작업 업데이트
    manager.update_task_history(task_id, f"진단 결과: {diagnosis}")
    
    # 수리 계획 수립
    repair_plan = "차량 진단 스캔 후 정확한 진단 필요"
    manager.update_task_history(task_id, f"수리 계획: {repair_plan}")
    
    return {
        "status": "success",
        "diagnosis": diagnosis,
        "repair_plan": repair_plan
    }


async def process_part_order(supplier: A2AAgent, task_id: str, part_number: str, quantity: int) -> Dict[str, Any]:
    """Parts Supplier가 부품 주문을 처리"""
    # 재고 데이터 (실제로는 데이터베이스에서 가져옴)
    inventory = {
        "12345": {"name": "스파크 플러그", "price": 50000, "stock": 15},
        "12346": {"name": "에어 필터", "price": 30000, "stock": 8},
        "12347": {"name": "연료 인젝터", "price": 120000, "stock": 4},
        "12348": {"name": "산소 센서", "price": 80000, "stock": 6},
    }
    
    # 부품 재고 확인
    if part_number not in inventory:
        supplier.update_task_history(task_id, f"부품 #{part_number} 재고 없음")
        return {"status": "error", "message": f"Part number {part_number} not found"}
    
    part_info = inventory[part_number]
    
    # 재고 수량 확인
    if part_info["stock"] < quantity:
        message = f"부품 #{part_number} 재고 부족 (요청: {quantity}, 가능: {part_info['stock']})"
        supplier.update_task_history(task_id, message)
        return {"status": "error", "message": message}
    
    # 주문 처리
    total_price = part_info["price"] * quantity
    
    # 작업 기록 업데이트
    supplier.update_task_history(
        task_id,
        f"부품 #{part_number} ({part_info['name']}) {quantity}개 주문 처리 완료. 총 가격: {total_price}원"
    )
    
    # 실제로는 여기서 재고를 차감하고 결제 처리
    
    return {
        "status": "success",
        "part_number": part_number,
        "part_name": part_info["name"],
        "quantity": quantity,
        "total_price": total_price,
        "order_id": "ORD-" + str(task_id)[-6:]
    }


# --------------- 메인 함수 ---------------

async def main():
    """메인 함수"""
    try:
        result = await auto_repair_shop_scenario()
        logger.info(f"시나리오 실행 결과: {result}")
    except Exception as e:
        logger.error(f"시나리오 실행 중 오류 발생: {str(e)}")


if __name__ == "__main__":
    # 비동기 이벤트 루프 실행
    asyncio.run(main()) 