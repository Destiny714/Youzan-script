# !/usr/bin/env python
# -*- coding: utf-8 -*-
# @Time    : 2021/10/27 10:28 下午
# @Author  : Destiny_
# @File    : captcha.py

import re
import json
import time
import encrypt
import pymysql
import requests
import schedule
import threading

captcha_map = {}
sid_list = encrypt.sid_list
aim_url = encrypt.aim_url
kdt_id = re.findall(r'kdt_id=(\d+?)&', aim_url)[0]


def header(sid):
    headers = {
        'content-type': 'application/json',
        'Extra-Data': '{"sid":"%s","clientType":"weapp-miniprogram","version":"2.87.8","client":"weapp","bizEnv":"wsc"}' % sid,
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.9(0x18000929) NetType/WIFI Language/zh_CN'
    }
    return headers

# 验证码生成器


def captcha_creater(sid):
    get_url = 'https://uic.youzan.com/passport/api/captcha/get-behavior-captcha-token-v2.json?app_id=wxdcc11cd7703c0e8d&kdt_id=44077958&access_token=&bizType=158&version=1.0'
    check_url = 'https://uic.youzan.com/passport/api/captcha/check-behavior-captcha-data.json?app_id=wxdcc11cd7703c0e8d&kdt_id=44077958&access_token='
    headers = header(sid)
    r = requests.get(url=get_url, headers=headers)
    try:
        r = r.json()
        token = r['data']['token']
        rdmstr = r['data']['randomStr']
        en_data = encrypt.encrypt(rdmstr)
        check_data = {
            "captchaType": 2,
            "token": token,
            "bizType": 158,
            "bizData": "{\"platform\":\"weapp\",\"buyer_id\":,\"order_receiver_phone\":\"\",\"book_key\":\"\",\"kdtId\":%s}" % kdt_id,
            "userBehaviorData": en_data
        }
        r = requests.post(url=check_url, headers=headers,
                          data=json.dumps(check_data))
        result = r.json()['data']['success']
        if result:
            captcha_map[sid] = token
            print('验证码生成完毕')
        else:
            print('验证码生成错误')
            captcha_map[sid] = ''
    except Exception as e:
        print(e)
        captcha_map[sid] = ''

# 多线程生成验证码


def make_captchas(sids: list):
    threads = []
    for sid in sids:
        thread = threading.Thread(target=captcha_creater(sid))
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()

# 生成验证码并存入数据库


def cpt():
    make_captchas(sid_list)
    push_to_mysql()

# 验证码存入数据库，数据库参数自行更改


def push_to_mysql():
    db = pymysql.connect(host='', port=3306, user='', password='', database='')
    cursor = db.cursor()
    select_sql = 'SELECT sid FROM 验证码table'
    cursor.execute(select_sql)
    _init_sid = cursor.fetchall()
    init_sid = [_[0] for _ in _init_sid]
    for sid in init_sid:
        if sid not in sid_list:
            delete_sql = 'DELETE FROM 验证码table WHERE sid=%s'
            cursor.execute(delete_sql, sid)
            db.commit()
    for sid in captcha_map:
        if sid in init_sid:
            add_sql = 'UPDATE 验证码table SET captcha=%s WHERE sid=%s'
            cursor.execute(add_sql, (captcha_map[sid], sid))
            db.commit()
        else:
            add_sql = 'INSERT INTO 验证码table (No,captcha,sid) VALUES (null,%s,%s)'
            cursor.execute(add_sql, (captcha_map[sid], sid))
            db.commit()
    cursor.close()
    db.close()
    print('\n验证码更新完成\n')

# 监控验证码是否有效


def refresh():
    db = pymysql.connect(host='', port=3306, user='', password='', database='')
    cursor = db.cursor()
    emergency_list = []
    select_sql = 'SELECT * FROM 验证码table'
    cursor.execute(select_sql)
    _ = cursor.fetchall()
    captchas = [[i[1], i[2]] for i in _]
    for _ in captchas:
        if _[1] == '0':
            emergency_list.append(_)
    cursor.close()
    db.close()
    if emergency_list:  # 如果验证码为空，则马上生成
        print('emergency!')
        cpt()


if __name__ == '__main__':
    cpt()
    schedule.every(1).seconds.do(refresh)  # 每秒刷新验证码有效性
    schedule.every(15).seconds.do(cpt)  # 每十五秒生成验证码
    while True:
        schedule.run_pending()
        time.sleep(0.01)
