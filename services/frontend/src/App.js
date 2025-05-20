import React, { useState, useEffect } from 'react';
import { 
  Container, 
  Box, 
  TextField, 
  Button, 
  Typography, 
  Paper,
  List,
  ListItem,
  ListItemText,
  Divider
} from '@mui/material';
import axios from 'axios';

const CHAT_GATEWAY_URL = 'http://localhost:8002';

function App() {
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [clientId] = useState(`client_${Math.random().toString(36).substr(2, 9)}`);

  useEffect(() => {
    const ws = new WebSocket(`ws://localhost:8002/ws/${clientId}`);

    ws.onmessage = (event) => {
      const response = JSON.parse(event.data);
      setMessages(prev => [...prev, {
        type: 'response',
        content: response.message,
        timestamp: new Date().toLocaleTimeString()
      }]);
    };

    return () => {
      ws.close();
    };
  }, [clientId]);

  const handleSendMessage = async () => {
    if (!inputMessage.trim()) return;

    const message = {
      client_id: clientId,
      message: inputMessage,
      message_type: 'chat'
    };

    try {
      await axios.post(`${CHAT_GATEWAY_URL}/messages`, message);
      setMessages(prev => [...prev, {
        type: 'user',
        content: inputMessage,
        timestamp: new Date().toLocaleTimeString()
      }]);
      setInputMessage('');
    } catch (error) {
      console.error('메시지 전송 실패:', error);
    }
  };

  return (
    <Container maxWidth="md">
      <Box sx={{ my: 4 }}>
        <Typography variant="h4" component="h1" gutterBottom align="center">
          자동차 정비 서비스
        </Typography>
        
        <Paper elevation={3} sx={{ p: 2, mb: 2, height: '60vh', overflow: 'auto' }}>
          <List>
            {messages.map((msg, index) => (
              <React.Fragment key={index}>
                <ListItem alignItems="flex-start">
                  <ListItemText
                    primary={msg.content}
                    secondary={msg.timestamp}
                    sx={{
                      textAlign: msg.type === 'user' ? 'right' : 'left',
                      backgroundColor: msg.type === 'user' ? '#e3f2fd' : '#f5f5f5',
                      borderRadius: 2,
                      p: 1
                    }}
                  />
                </ListItem>
                <Divider variant="inset" component="li" />
              </React.Fragment>
            ))}
          </List>
        </Paper>

        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField
            fullWidth
            variant="outlined"
            placeholder="메시지를 입력하세요..."
            value={inputMessage}
            onChange={(e) => setInputMessage(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
          />
          <Button 
            variant="contained" 
            onClick={handleSendMessage}
            disabled={!inputMessage.trim()}
          >
            전송
          </Button>
        </Box>
      </Box>
    </Container>
  );
}

export default App; 