# 股票双策略回测系统 (strategy_timer)

## 项目简介
基于 TSLA、AZO、ORLY 三只股票的双策略回测系统：
- **均线策略**：MA5/MA30 金叉死叉轮动
- **温度计策略**：自定义多因子温度计指标状态机

## 策略逻辑

### 均线策略 (MA5/MA30)
- 金叉 (MA5 > MA30)：全仓买入 TSLA
- 死叉 (MA5 < MA30)：清仓 TSLA，买入 AZO + ORLY 避险

### 温度计策略
- 多因子合成指标：RSI + WR + CMO + KD + TSI + ADX
- 阈值配置：
  - 低温区：20-50°C → TSLA_LOW
  - 高温区：> 76°C → TSLA_HIGH
  - 跌破 66°C 退出高温区

## 运行方式

### 本地运行
```bash
cd strategy_timer
python strategy.py