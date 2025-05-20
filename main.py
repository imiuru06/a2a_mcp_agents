#!/usr/bin/env python3
"""
A2A와 MCP 프로토콜을 사용한 자동차 수리점 시나리오 구현 예제
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any, Union
from enum import Enum

# ----- MCP 프로토콜 구현 -----

class MCP:
    """Model Context Protocol (MCP) 구현"""
    
    @staticmethod
    def tool_call(tool_name: str, **kwargs) -> Dict[str, Any]:
        """MCP 방식으로 도구를 호출합니다"""
        call_id = str(uuid.uuid4())
        return {
            "call_id": call_id,
            "tool_name": tool_name,
            "parameters": kwargs
        }
    
    @staticmethod
    def tool_response(call_id: str, result: Any) -> Dict[str, Any]:
        """MCP 도구 호출 응답을 생성합니다"""
        return {
            "call_id": call_id,
            "status": "success",
            "result": result
        }


# ----- A2A 프로토콜 구현 -----

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class AgentCard:
    """에이전트 카드 정의 - A2A 프로토콜의 일부"""
    agent_id: str
    name: str
    description: str
    skills: List[str]
    supported_modalities: List[str] = field(default_factory=lambda: ["text"])


@dataclass
class Task:
    """A2A 작업 정의"""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_by: str = ""
    assigned_to: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    history: List[Dict[str, Any]] = field(default_factory=list)


class A2AAgent:
    """A2A 프로토콜을 구현한 기본 에이전트"""
    
    def __init__(self, agent_id: str, name: str, description: str, skills: List[str]):
        self.agent_card = AgentCard(
            agent_id=agent_id,
            name=name,
            description=description,
            skills=skills
        )
        self.tasks: Dict[str, Task] = {}
        self.mcp_tools: Dict[str, callable] = {}
    
    def register_mcp_tool(self, tool_name: str, tool_function: callable):
        """MCP 도구를 등록합니다"""
        self.mcp_tools[tool_name] = tool_function
    
    def get_agent_card(self) -> Dict[str, Any]:
        """에이전트 카드를 가져옵니다"""
        return asdict(self.agent_card)
    
    def create_task(self, title: str, description: str, context: Dict[str, Any] = None) -> str:
        """새 작업을 생성합니다"""
        task = Task(
            title=title,
            description=description,
            created_by=self.agent_card.agent_id,
            context=context or {}
        )
        self.tasks[task.task_id] = task
        return task.task_id
    
    def assign_task(self, task_id: str, agent_id: str) -> bool:
        """작업을 다른 에이전트에 할당합니다"""
        if task_id in self.tasks:
            self.tasks[task_id].assigned_to = agent_id
            self.tasks[task_id].status = TaskStatus.IN_PROGRESS
            return True
        return False
    
    def update_task(self, task_id: str, status: TaskStatus = None, message: str = None) -> bool:
        """작업 상태를 업데이트합니다"""
        if task_id not in self.tasks:
            return False
        
        if status:
            self.tasks[task_id].status = status
        
        if message:
            self.tasks[task_id].history.append({
                "agent_id": self.agent_card.agent_id,
                "message": message,
                "timestamp": str(uuid.uuid4())  # 실제로는 시간 사용
            })
        
        return True
    
    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """작업 정보를 가져옵니다"""
        if task_id in self.tasks:
            return asdict(self.tasks[task_id])
        return None
    
    def call_mcp_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """MCP 도구를 호출합니다"""
        if tool_name not in self.mcp_tools:
            return {"status": "error", "message": f"Tool {tool_name} not found"}
        
        call = MCP.tool_call(tool_name, **kwargs)
        try:
            result = self.mcp_tools[tool_name](**kwargs)
            return MCP.tool_response(call["call_id"], result)
        except Exception as e:
            return {
                "call_id": call["call_id"],
                "status": "error",
                "message": str(e)
            }
    
    def communicate(self, to_agent_id: str, task_id: str, message: str) -> Dict[str, Any]:
        """다른 에이전트와 통신합니다"""
        if task_id not in self.tasks:
            return {"status": "error", "message": f"Task {task_id} not found"}
        
        self.update_task(task_id, message=message)
        return {
            "status": "success",
            "message": f"Message sent to {to_agent_id} for task {task_id}"
        }


# ----- 구체적인 에이전트 구현 -----

class ShopManagerAgent(A2AAgent):
    """자동차 수리점 매니저 에이전트"""
    
    def __init__(self):
        super().__init__(
            agent_id="shop_manager_001",
            name="Shop Manager",
            description="자동차 수리점을 관리하고 고객과 소통하는 에이전트",
            skills=["customer_service", "task_delegation", "problem_diagnosis"]
        )
    
    def diagnose_issue(self, task_id: str, symptoms: List[str]) -> Dict[str, Any]:
        """고객 문제를 진단하고 적절한 정비사에게 할당합니다"""
        if task_id not in self.tasks:
            return {"status": "error", "message": "Task not found"}
        
        # 여기서 증상에 따라 적절한 진단을 수행할 수 있습니다
        diagnosis = f"증상 분석: {', '.join(symptoms)}"
        self.update_task(task_id, message=f"진단 결과: {diagnosis}")
        
        # 수리 계획 수립
        repair_plan = "차량 검사 후 정확한 진단 필요"
        self.update_task(task_id, message=f"수리 계획: {repair_plan}")
        
        return {
            "status": "success",
            "diagnosis": diagnosis,
            "repair_plan": repair_plan
        }
    
    def assign_to_mechanic(self, task_id: str, mechanic_id: str) -> Dict[str, Any]:
        """작업을 특정 정비사에게 할당합니다"""
        if self.assign_task(task_id, mechanic_id):
            return {"status": "success", "message": f"Task assigned to mechanic {mechanic_id}"}
        return {"status": "error", "message": "Failed to assign task"}


class MechanicAgent(A2AAgent):
    """자동차 정비사 에이전트"""
    
    def __init__(self):
        super().__init__(
            agent_id="mechanic_001",
            name="Auto Mechanic",
            description="자동차 진단 및 수리를 수행하는 정비사 에이전트",
            skills=["car_diagnosis", "car_repair", "parts_replacement"]
        )
        
        # MCP 도구들 등록
        self.register_mcp_tool("scan_vehicle", self.scan_vehicle_for_error_codes)
        self.register_mcp_tool("get_repair_procedure", self.get_repair_procedure)
        self.register_mcp_tool("raise_platform", self.raise_platform)
    
    def scan_vehicle_for_error_codes(self, vehicle_id: str) -> Dict[str, Any]:
        """차량 진단 스캐너 도구 (MCP)"""
        # 실제로는 실제 스캐너 장치와 연결될 수 있음
        return {
            "error_codes": ["P0300", "P0171"],
            "descriptions": {
                "P0300": "Random/Multiple Cylinder Misfire Detected",
                "P0171": "System Too Lean (Bank 1)"
            }
        }
    
    def get_repair_procedure(self, error_code: str, vehicle_make: str, vehicle_model: str) -> Dict[str, Any]:
        """수리 매뉴얼 데이터베이스 도구 (MCP)"""
        # 실제로는 데이터베이스 쿼리를 수행할 수 있음
        procedures = {
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
        
        if error_code in procedures:
            return {
                "error_code": error_code,
                "vehicle": f"{vehicle_make} {vehicle_model}",
                "procedure": procedures[error_code]
            }
        return {"error": "Procedure not found"}
    
    def raise_platform(self, height_meters: float) -> Dict[str, Any]:
        """차량 리프트 플랫폼 도구 (MCP)"""
        # 실제로는 물리적 장치를 제어할 수 있음
        if 0 <= height_meters <= 2.5:
            return {
                "status": "success",
                "current_height": height_meters,
                "max_height": 2.5
            }
        return {"status": "error", "message": "Invalid height requested"}
    
    def perform_repair(self, task_id: str) -> Dict[str, Any]:
        """수리를 수행합니다 (A2A 작업)"""
        if task_id not in self.tasks:
            return {"status": "error", "message": "Task not found"}
        
        # 1. 차량 스캔 (MCP 도구 사용)
        vehicle_id = self.tasks[task_id].context.get("vehicle_id", "unknown")
        scan_result = self.call_mcp_tool("scan_vehicle", vehicle_id=vehicle_id)
        
        # 2. 수리 절차 가져오기 (MCP 도구 사용)
        if scan_result["status"] == "success" and scan_result["result"]["error_codes"]:
            error_code = scan_result["result"]["error_codes"][0]
            vehicle_info = self.tasks[task_id].context.get("vehicle_info", {})
            
            procedure_result = self.call_mcp_tool(
                "get_repair_procedure",
                error_code=error_code,
                vehicle_make=vehicle_info.get("make", "Generic"),
                vehicle_model=vehicle_info.get("model", "Car")
            )
            
            # 3. 리프트 올리기 (MCP 도구 사용)
            lift_result = self.call_mcp_tool("raise_platform", height_meters=1.5)
            
            # 4. 작업 업데이트
            self.update_task(
                task_id,
                message=f"수리 진행 중: 오류 코드 {error_code}에 대한 수리 절차 진행 중"
            )
            
            # 수리가 완료되었다고 가정
            self.update_task(task_id, status=TaskStatus.COMPLETED, message="수리가 완료되었습니다")
            
            return {
                "status": "success",
                "error_codes": scan_result["result"]["error_codes"],
                "repair_completed": True
            }
        
        return {"status": "error", "message": "Failed to diagnose vehicle"}


class PartsSupplierAgent(A2AAgent):
    """부품 공급업체 에이전트"""
    
    def __init__(self):
        super().__init__(
            agent_id="parts_supplier_001",
            name="Parts Supplier",
            description="자동차 부품을 공급하는 에이전트",
            skills=["parts_inventory", "pricing", "ordering"]
        )
        self.inventory = {
            "12345": {"name": "스파크 플러그", "price": 50000, "stock": 15},
            "12346": {"name": "에어 필터", "price": 30000, "stock": 8},
            "12347": {"name": "연료 인젝터", "price": 120000, "stock": 4},
            "12348": {"name": "산소 센서", "price": 80000, "stock": 6},
        }
    
    def check_inventory(self, part_number: str) -> Dict[str, Any]:
        """재고 확인"""
        if part_number in self.inventory:
            return {
                "status": "success",
                "part_number": part_number,
                "part_info": self.inventory[part_number]
            }
        return {
            "status": "error",
            "message": f"Part number {part_number} not found"
        }
    
    def order_part(self, task_id: str, part_number: str, quantity: int = 1) -> Dict[str, Any]:
        """부품 주문 처리"""
        inventory_check = self.check_inventory(part_number)
        
        if inventory_check["status"] == "error":
            self.update_task(task_id, message=f"부품 #{part_number} 재고 없음")
            return inventory_check
        
        if inventory_check["part_info"]["stock"] < quantity:
            self.update_task(
                task_id,
                message=f"부품 #{part_number} 재고 부족 (요청: {quantity}, 가능: {inventory_check['part_info']['stock']})"
            )
            return {
                "status": "error",
                "message": f"Insufficient stock (requested: {quantity}, available: {inventory_check['part_info']['stock']})"
            }
        
        # 주문 처리 (실제로는 여기서 재고를 차감함)
        total_price = inventory_check["part_info"]["price"] * quantity
        
        self.update_task(
            task_id,
            message=f"부품 #{part_number} ({inventory_check['part_info']['name']}) {quantity}개 주문 완료. 총 가격: {total_price}원"
        )
        
        return {
            "status": "success",
            "part_number": part_number,
            "part_name": inventory_check["part_info"]["name"],
            "quantity": quantity,
            "total_price": total_price,
            "order_id": str(uuid.uuid4())
        }


# ----- 시나리오 실행 예제 -----

def run_auto_repair_scenario():
    """자동차 수리점 시나리오 실행"""
    # 1. 에이전트 생성
    shop_manager = ShopManagerAgent()
    mechanic = MechanicAgent()
    parts_supplier = PartsSupplierAgent()
    
    print("=== 자동차 수리점 시나리오 ===")
    print("1. 고객이 Shop Manager 에이전트와 상호작용 (A2A 프로토콜)")
    
    # 2. 고객이 문제 보고 (A2A 프로토콜을 통해)
    task_id = shop_manager.create_task(
        title="차에서 소음 발생",
        description="차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.",
        context={
            "customer_id": "customer_123",
            "vehicle_id": "VIN_XYZ123",
            "vehicle_info": {
                "make": "Toyota",
                "model": "Camry",
                "year": 2018
            }
        }
    )
    
    print(f"   - 작업 생성: {task_id}")
    
    # 3. Shop Manager가 문제 진단
    diagnosis_result = shop_manager.diagnose_issue(
        task_id=task_id, 
        symptoms=["엔진 소음", "경고등 점등"]
    )
    print(f"   - 진단 결과: {diagnosis_result['diagnosis']}")
    print(f"   - 수리 계획: {diagnosis_result['repair_plan']}")
    
    # 4. Shop Manager가 Mechanic에게 작업 할당 (A2A 프로토콜)
    assign_result = shop_manager.assign_to_mechanic(task_id, mechanic.agent_card.agent_id)
    print(f"   - 정비사 할당: {assign_result['message']}")
    
    # 5. 작업 정보를 Mechanic에게 전달 (실제 환경에서는 A2A 서버가 처리)
    mechanic.tasks[task_id] = shop_manager.tasks[task_id]
    
    print("\n2. 정비사가 MCP 도구를 사용하여 차량 진단 및 수리")
    
    # 6. Mechanic이 MCP 도구를 사용하여 수리 수행
    repair_result = mechanic.perform_repair(task_id)
    
    if repair_result["status"] == "success":
        print(f"   - 발견된 오류 코드: {repair_result['error_codes']}")
        print(f"   - 수리 완료 여부: {'예' if repair_result['repair_completed'] else '아니오'}")
    
    # 7. 부품이 필요하여 Parts Supplier와 A2A로 통신
    print("\n3. 정비사가 Parts Supplier 에이전트와 A2A로 통신하여 부품 주문")
    
    # A2A 통신을 통해 작업 생성 (실제로는 A2A 서버가 중계)
    parts_task_id = mechanic.create_task(
        title="부품 주문 요청",
        description="Toyota Camry 2018 수리에 필요한 부품 주문",
        context={"repair_task_id": task_id}
    )
    
    # Parts Supplier에게 작업 할당 (실제로는 A2A 통신)
    parts_supplier.tasks[parts_task_id] = mechanic.tasks[parts_task_id]
    
    # Mechanic이 Parts Supplier에게 메시지 전송 (A2A 프로토콜)
    mechanic.communicate(
        to_agent_id=parts_supplier.agent_card.agent_id,
        task_id=parts_task_id,
        message="스파크 플러그(부품 #12345) 4개가 필요합니다."
    )
    
    # Parts Supplier가 주문 처리 (A2A 작업)
    order_result = parts_supplier.order_part(parts_task_id, "12345", 4)
    
    print(f"   - 부품 주문 결과: {order_result['part_name']} {order_result['quantity']}개")
    print(f"   - 총 가격: {order_result['total_price']}원")
    print(f"   - 주문 ID: {order_result['order_id']}")
    
    print("\n=== 시나리오 완료 ===")


if __name__ == "__main__":
    run_auto_repair_scenario()
