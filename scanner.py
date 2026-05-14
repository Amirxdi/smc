#!/usr/bin/env python3
"""
Scanner module for detecting price touches on previous candle high/low.
"""

import asyncio
from ai_analyzer import AIAnalyzer


class Scanner:
    """Scans markets for price touches on previous candle levels."""
    
    def __init__(self, market):
        """Initialize scanner with market instance."""
        self.market = market
        self.ai_analyzer = AIAnalyzer()
    
    async def scan_symbol(self, symbol):
        """
        Scan a single symbol for price touches.
        
        Args:
            symbol (str): Trading pair symbol (e.g., 'BTC/USDT')
        
        Returns:
            dict or None: Touch information if detected, None otherwise
        """
        # Fetch last 2 candles (current and previous)
        candles = await self.market.fetch_4h_candles(symbol, limit=2)
        
        if len(candles) < 2:
            return None
        
        # Parse candles
        # candles format: [timestamp, open, high, low, close, volume]
        previous_candle = candles[-2]  # Previous completed candle
        current_candle = candles[-1]   # Current forming candle
        
        prev_high = previous_candle[2]
        prev_low = previous_candle[3]
        current_price = current_candle[4]  # Current close price
        
        # Check if current price touches previous high or low
        # We use a small tolerance (0.1%) to account for price precision
        tolerance = prev_high * 0.001  # 0.1% tolerance
        
        touch_high = abs(current_price - prev_high) <= tolerance
        touch_low = abs(current_price - prev_low) <= tolerance
        
        if touch_high or touch_low:
            return {
                'symbol': symbol,
                'current_price': current_price,
                'prev_high': prev_high,
                'prev_low': prev_low,
                'touch_high': touch_high,
                'touch_low': touch_low
            }
        
        return None
    
    async def scan_all(self, symbols):
        """
        Scan all symbols for price touches.
        
        Args:
            symbols (list): List of trading pair symbols
        
        Returns:
            list: List of detected touches
        """
        touches = []
        
        print(f"\nScanning {len(symbols)} symbols...")
        
        # Scan symbols concurrently (in batches to avoid rate limits)
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            tasks = [self.scan_symbol(symbol) for symbol in batch]
            results = await asyncio.gather(*tasks)
            
            for result in results:
                if result:
                    touches.append(result)
            
            # Small delay between batches to respect rate limits
            if i + batch_size < len(symbols):
                await asyncio.sleep(1)
        
        return touches
    
    def print_touches(self, touches, analyses=None):
        """Print detected touches in a readable format."""
        if not touches:
            print("\nNo price touches detected.")
            return
        
        print(f"\n{'='*60}")
        print(f"Detected {len(touches)} price touch(es):")
        print(f"{'='*60}")
        
        for touch in touches:
            symbol = touch['symbol']
            price = touch['current_price']
            
            if touch['touch_high']:
                print(f"🔺 {symbol}: Price {price:.2f} touched previous HIGH {touch['prev_high']:.2f}")
            
            if touch['touch_low']:
                print(f"🔻 {symbol}: Price {price:.2f} touched previous LOW {touch['prev_low']:.2f}")
            
            # Add AI analysis if available
            if analyses and symbol in analyses:
                print(f"   🤖 AI: {analyses[symbol]}")
        
        print(f"{'='*60}\n")
