#!/usr/bin/env python3
"""
AI Analyzer module using DeepSeek API for market analysis.
"""

import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()


class AIAnalyzer:
    """Analyzes market touches using DeepSeek AI."""
    
    def __init__(self):
        """Initialize the AI analyzer with DeepSeek API key."""
        self.api_key = os.getenv('DEEPSEEK_API_KEY', '')
        self.api_url = 'https://api.deepseek.com/v1/chat/completions'
    
    async def analyze_touch(self, touch_data):
        """
        Analyze a price touch event using DeepSeek AI.
        
        Args:
            touch_data (dict): Dictionary containing touch information
                - symbol: Trading pair symbol
                - current_price: Current price
                - prev_high: Previous candle high
                - prev_low: Previous candle low
                - touch_high: Whether price touched high
                - touch_low: Whether price touched low
        
        Returns:
            str: AI analysis text or None if error
        """
        if not self.api_key:
            return "AI analysis unavailable: No API key configured"
        
        # Build prompt for AI
        symbol = touch_data['symbol']
        price = touch_data['current_price']
        
        if touch_data['touch_high']:
            level = f"previous HIGH at {touch_data['prev_high']:.2f}"
            direction = "resistance"
        else:
            level = f"previous LOW at {touch_data['prev_low']:.2f}"
            direction = "support"
        
        prompt = f"""Analyze this crypto futures market event:

Symbol: {symbol}
Current Price: {price:.2f}
Event: Price touched {level}

Provide a brief, beginner-friendly analysis (max 2 sentences) about what this might mean for traders. Focus on {direction} implications."""
        
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                }
                
                payload = {
                    'model': 'deepseek-chat',
                    'messages': [
                        {
                            'role': 'system',
                            'content': 'You are a helpful crypto trading assistant. Provide concise, beginner-friendly market analysis.'
                        },
                        {
                            'role': 'user',
                            'content': prompt
                        }
                    ],
                    'max_tokens': 150,
                    'temperature': 0.7
                }
                
                async with session.post(self.api_url, headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['choices'][0]['message']['content'].strip()
                    else:
                        error_text = await response.text()
                        print(f"DeepSeek API error: {response.status} - {error_text}")
                        return None
                        
        except Exception as e:
            print(f"Error calling DeepSeek API: {e}")
            return None
    
    async def analyze_multiple(self, touches):
        """
        Analyze multiple touch events concurrently.
        
        Args:
            touches (list): List of touch data dictionaries
        
        Returns:
            dict: Mapping of symbol to analysis text
        """
        analyses = {}
        
        # Analyze each touch
        for touch in touches:
            symbol = touch['symbol']
            analysis = await self.analyze_touch(touch)
            if analysis:
                analyses[symbol] = analysis
        
        return analyses
