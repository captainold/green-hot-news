#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日发布调度提醒的执行说明（reminder prompt 引用）。

实际调度：会话 schedule_create 每日 08:35 触发，prompt 引导 agent 执行：
    1. python scripts/publish/daily_publish.py --all --refresh
    2. 检查产物 data/publish/<今天>/（digest.json + xhs/*.png + 两平台文案）
    3. 向用户报告精选头条与卡片段落，等待确认发布
"""
