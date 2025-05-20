// Vue 애플리케이션 생성
const app = Vue.createApp({
  data() {
    return {
      // 탭 관리
      activeTab: 'new-task',
      
      // API URL
      apiUrl: '',
      
      // 새 작업 등록
      newTask: {
        customer_id: `customer_${Date.now()}`,
        vehicle_id: `VIN_${Date.now()}`,
        vehicle_info: {
          make: '현대',
          model: '소나타',
          year: 2020
        },
        description: '차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.',
        symptoms: ['엔진 소음']
      },
      availableSymptoms: [
        "엔진 소음", "엔진 경고등", "과열", "시동 문제", "제동 문제",
        "변속 문제", "연비 저하", "배기가스 문제", "전기 시스템 문제", "기타"
      ],
      isSubmitting: false,
      taskSuccess: null,
      taskError: null,
      
      // 작업 현황
      tasks: [],
      tasksLoading: false,
      selectedTask: null,
      
      // 부품 주문
      partOrder: {
        task_id: '',
        part_number: '12345',
        quantity: 1
      },
      isOrdering: false,
      orderSuccess: null,
      orderError: null,
      
      // 에이전트 정보
      agents: [],
      agentsLoading: false,
      
      // 설정
      settingsSuccess: false
    };
  },
  
  methods: {
    // 날짜 포맷팅
    formatDate(dateStr) {
      if (!dateStr) return '-';
      try {
        const date = new Date(dateStr);
        return date.toLocaleString('ko-KR', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit'
        });
      } catch (error) {
        return dateStr;
      }
    },
    
    // 새 작업 등록
    async submitTask() {
      this.isSubmitting = true;
      this.taskSuccess = null;
      this.taskError = null;
      
      try {
        const result = await window.electronAPI.createTask({
          customer_id: this.newTask.customer_id,
          vehicle_id: this.newTask.vehicle_id,
          vehicle_info: this.newTask.vehicle_info,
          description: this.newTask.description,
          symptoms: this.newTask.symptoms
        });
        
        if (result.error) {
          this.taskError = result.error;
        } else {
          this.taskSuccess = result;
          
          // 작업 정보 가져오기
          const taskInfo = await window.electronAPI.getTask(result.task_id);
          if (!taskInfo.error) {
            this.tasks.push(taskInfo);
            // 초기화
            this.newTask = {
              customer_id: `customer_${Date.now()}`,
              vehicle_id: `VIN_${Date.now()}`,
              vehicle_info: {
                make: '현대',
                model: '소나타',
                year: 2020
              },
              description: '차에서 덜컹거리는 소리가 나고 엔진 경고등이 켜졌습니다.',
              symptoms: ['엔진 소음']
            };
          }
        }
      } catch (error) {
        this.taskError = error.message || '작업 등록 중 오류가 발생했습니다.';
      } finally {
        this.isSubmitting = false;
      }
    },
    
    // 작업 보기
    viewTask(taskId) {
      this.activeTab = 'tasks';
      this.viewTaskDetails(taskId);
    },
    
    // 작업 목록 새로고침
    async refreshTasks() {
      this.tasksLoading = true;
      
      try {
        // 모든 작업에 대해 최신 정보 가져오기
        const updatedTasks = [];
        
        for (const task of this.tasks) {
          const taskInfo = await window.electronAPI.getTask(task.task_id);
          if (!taskInfo.error) {
            updatedTasks.push(taskInfo);
          }
        }
        
        this.tasks = updatedTasks;
        
        // 선택된 작업이 있으면 그 정보도 업데이트
        if (this.selectedTask) {
          const updatedTask = this.tasks.find(t => t.task_id === this.selectedTask.task_id);
          if (updatedTask) {
            this.selectedTask = updatedTask;
          }
        }
      } catch (error) {
        console.error('작업 목록 새로고침 중 오류:', error);
      } finally {
        this.tasksLoading = false;
      }
    },
    
    // 작업 상세 정보 보기
    async viewTaskDetails(taskId) {
      this.tasksLoading = true;
      
      try {
        const taskInfo = await window.electronAPI.getTask(taskId);
        if (!taskInfo.error) {
          this.selectedTask = taskInfo;
          this.partOrder.task_id = taskId;
        }
      } catch (error) {
        console.error('작업 상세 정보 조회 중 오류:', error);
      } finally {
        this.tasksLoading = false;
      }
    },
    
    // 부품 주문
    async orderPart() {
      if (!this.partOrder.task_id) return;
      
      this.isOrdering = true;
      this.orderSuccess = null;
      this.orderError = null;
      
      try {
        const result = await window.electronAPI.orderParts(this.partOrder);
        
        if (result.error) {
          this.orderError = result.error;
        } else {
          this.orderSuccess = result;
          
          // 작업 정보 새로고침
          await this.viewTaskDetails(this.partOrder.task_id);
        }
      } catch (error) {
        this.orderError = error.message || '부품 주문 중 오류가 발생했습니다.';
      } finally {
        this.isOrdering = false;
      }
    },
    
    // 에이전트 정보 새로고침
    async refreshAgents() {
      this.agentsLoading = true;
      
      try {
        const agents = await window.electronAPI.getAgents();
        if (!agents.error) {
          this.agents = agents;
        }
      } catch (error) {
        console.error('에이전트 정보 새로고침 중 오류:', error);
      } finally {
        this.agentsLoading = false;
      }
    },
    
    // 설정 저장
    async saveSettings() {
      this.settingsSuccess = false;
      
      try {
        const result = await window.electronAPI.setApiUrl(this.apiUrl);
        if (result.success) {
          this.settingsSuccess = true;
        }
      } catch (error) {
        console.error('설정 저장 중 오류:', error);
      }
    },
    
    // 초기 데이터 로드
    async loadInitialData() {
      // API URL 가져오기
      try {
        this.apiUrl = await window.electronAPI.getApiUrl();
      } catch (error) {
        console.error('API URL 가져오기 실패:', error);
      }
      
      // 에이전트 정보 가져오기
      await this.refreshAgents();
    }
  },
  
  mounted() {
    // 초기 데이터 로드
    this.loadInitialData();
    
    // 5초마다 자동 새로고침 (실제 앱에서는 WebSocket 등을 사용하는 것이 좋음)
    this.refreshInterval = setInterval(() => {
      if (this.activeTab === 'tasks' && this.tasks.length > 0) {
        this.refreshTasks();
      }
    }, 5000);
  },
  
  beforeUnmount() {
    // 인터벌 정리
    if (this.refreshInterval) {
      clearInterval(this.refreshInterval);
    }
  }
});

// Vue 앱 마운트
app.mount('#app'); 