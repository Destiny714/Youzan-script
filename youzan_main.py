import re
import json
import time
import random
import pymysql
import encrypt
import schedule
import datetime
import warnings
import requests
import threading

warnings.filterwarnings('ignore')

y = True  # 忽略，倒计时用
proxies = []  # 可手动添加，可通过url添加
good_id = ''  # 商品id，自动读取
sku_map = {}
uid_dict = {}
add_dict = {}  # 地址map
buy_time = {}
rub_list = []  # 无效账号列表
all_stock = 0  # 总库存，自动读取
sold_time = 0  # 开售时间，自动读取
choose_sku = ''
captcha_map = {}  # 验证码map
available_sku = []  # 监控刷新可购买列表
kdt_id = re.findall(r'kdt_id=(\d+?)&', encrypt.aim_url)[0]  # 自动读取商户kdtid

# proxy获取，根据需求更改


def get_proxy():
    global proxies
    proxies = []
    url = ''  # proxy pool url
    r = requests.get(url).text
    proxy_list = r.split('\n')
    for _ in proxy_list:
        proxy = {
            'http': f'http:{_}',
            'https': f'http:{_}'
        }
        try:
            r = requests.get(url='https://www.baidu.com',
                             proxies=proxy, timeout=0.5)
            if r.status_code == 200:
                print(f'pass proxy---{proxy}')
                proxies.append(proxy)
        except Exception as e:
            print('bad proxy', e)
            pass

# 用户header


def header(sid):
    headers = {
        'content-type': 'application/json',
        'Extra-Data': '{"sid":"%s","clientType":"weapp-miniprogram","version":"2.87.8","client":"weapp","bizEnv":"wsc"}' % sid,
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.9(0x18000929) NetType/WIFI Language/zh_CN'
    }
    return headers

# 从数据库读取验证码，也可以用redis、sqlite等其他数据库


def read_captcha():
    db = pymysql.connect(host='', port=3306, user='',
                         password='', database='')
    cursor = db.cursor()
    global captcha_map
    select_sql = 'SELECT * FROM 验证码table'
    cursor.execute(select_sql)
    _ = cursor.fetchall()
    captcha_map = {i[1]: i[2] for i in _}
    cursor.close()
    db.close()

# 验证码table作废，为下次启动备用


def zero_fill():
    db = pymysql.connect(host='', port=3306, user='',
                         password='', database='')
    cursor = db.cursor()
    add_sql = 'UPDATE 验证码table SET captcha=0'
    cursor.execute(add_sql)
    db.commit()
    cursor.close()
    db.close()

# 读取商品详情


def get_detail():
    global kdt_id, good_id, all_stock, t, sold_time, sku_map
    url = aim_url
    sku_map = {}
    headers = header('')
    try:
        r = requests.get(url=url, headers=headers)
        r = r.json()
        skuinfo = r['data']['goodsData']['skuInfo']
        all_stock = skuinfo['spuStock']['stockNum']
        kdt_id = r['data']['shopMetaInfo']['kdtId']
        good_id = r['data']['goodsData']['goods']['id']
        features = skuinfo['props']
        sold_time = r['data']['goodsData']['goods']['startSoldTime']
        sku_name = r['data']['goodsData']['goods']['title']
        if not features:
            sku_price = skuinfo['spuPrice']['price']
            sku_id = skuinfo['spuPrice']['skuId']
            sku_stock = skuinfo['spuStock']['stockNum']
            sku_map[sku_id] = {'stock': sku_stock,
                               'price': sku_price, 'name': sku_name}
        else:
            sku_price = skuinfo['skuPrices']
            sku_stock = skuinfo['skuStocks']
            feature_skus = skuinfo['skus']
            id_stock_map = {_['skuId']: _['stockNum'] for _ in sku_stock}
            id_price_map = {_['skuId']: _['price'] for _ in sku_price}
            feature_map = {str(v['id']): v['name']
                           for feature in features for v in feature['v']}
            key_map = {feature['k_s']: feature['k'] for feature in features}
            for feature_sku in feature_skus:
                skuId = feature_sku['skuId']
                del feature_sku['skuId']
                sku_map[skuId] = {key_map[key]: feature_map[feature_sku[key]] for key in feature_sku if
                                  feature_sku[key] != '0'}
            for _ in id_price_map:
                sku_map[_]['price'] = id_price_map[_] / 100
            for _ in id_stock_map:
                sku_map[_]['stock'] = id_stock_map[_]
    except Exception as e:
        sku_name = '商品读取失败'
        print(e)
        pass
    if t == 0:
        print(sku_name + '\n')
        t += 1

# 获取账户地址


def get_address():
    global rub_list
    for sid in sid_list:
        url = 'https://cashier.youzan.com/wsctrade/uic/address/getAddressList.json'
        headers = header(sid)
        try:
            r = requests.post(url=url, headers=headers,
                              data=json.dumps({}), timeout=3).json()
            if r['data']:
                address = r['data'][0]
                uid_dict[sid] = address['userId']
                address['recipients'] = address['userName']
                address['addressId'] = address['id']
                add_dict[sid] = address
                print(address['userName'])
            else:
                print('无默认地址')
                rub_list.append(sid)
            time.sleep(0.5)
        except Exception as e:
            print(e)
            rub_list.append(sid)
    if rub_list:
        print(f'{len(rub_list)}个号无默认地址，删除')
        for _ in rub_list:
            sid_list.remove(_)
        rub_list = []
    print(f'\n{len(sid_list)}个有效账户\n')

# 下单


def create_order(sid, sku):
    headers = header(sid)
    data = {
        "version": 2,
        "source": {
            "bookKey": "",
            "clientIp": "",
            "fromThirdApp": False,
            "isWeapp": True,
            "itemSources": [{
                "activityId": 0,
                "activityType": 0,
                "bizTracePointExt": "{\"yai\":\"wsc_c\",\"st\":\"weapp\",\"is_share\":\"1\",\"sv\":\"2.1.22\",\"atr_uuid\":\"\",\"page_type\":\"\",\"banner_id\":\"f.85245649~goods.1~9~OwI3Koqu\",\"yzk_ex\":\"\",\"tui_platform\":\"\",\"tui_click\":\"\",\"uuid\":\"\",\"userId\":%s,\"platform\":\"weapp\",\"scene\":1008,\"slg\":\"tagGoodList-default,OpBottom,uuid,abTraceId\",\"from_source\":\"\",\"weapp_version\":\"2.87.8\",\"alg_id\":\"0\",\"appId\":\"wx18eae5eb4a5bec48\",\"alias\":\"%s\",\"wecom_uuid\":\"\",\"wecom_chat_id\":\"\"}" %
                                    (uid_dict[sid], alias),
                "cartCreateTime": 0,
                "cartUpdateTime": 0,
                "gdtId": "",
                "goodsId": good_id,
                "pageSource": "",
                "propertyIds": [],
                "skuId": sku
            }],
            "kdtSessionId": sid,
            "needAppRedirect": False,
            "orderFrom": "",
            "orderType": 0,
            "platform": "weapp",
            "salesman": "",
            "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 11_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E217 MicroMessenger/6.8.0(0x16080000) NetType/WIFI Language/en Branch/Br_trunk MiniProgramEnv/Mac",
            "orderMark": "wx_shop",
            "weAppFormId": "1c5c5b59b4db4bc3a519bd10eb39ecc1"
        },
        "config": {
            "containsUnavailableItems": False,
            "fissionActivity": {
                "fissionTicketNum": 0
            },
            "paymentExpiry": 0,
            "receiveMsg": True,
            "usePoints": False,
            "useWxpay": True,
            "buyerMsg": "",
            "disableStoredDiscount": True,
            "storedDiscountRechargeGuide": True
        },
        "usePayAsset": {},
        "items": [{
            "activityId": 0,
            "activityType": 0,
            "deliverTime": 0,
            "extensions": {
                "OUTER_ITEM_ID": "10000"
            },
            "goodsId": good_id,
            "isInstallment": False,
            "isSevenDayUnconditionalReturn": False,
            "itemFissionTicketsNum": 0,
            "kdtId": kdt_id,
            "num": b_num,
            "pointsPrice": 0,
            "price": int(sku_map[sku]['price'] * b_num),
            "propertyIds": [],
            "skuId": sku,
            "storeId": 0,
            "umpSkuId": 0
        }],
        "seller": {
            "kdtId": kdt_id,
            "storeId": 0
        },
        "ump": {
            "activities": [{
                "activityId": 0,
                "activityType": 0,
                "externalPointId": 0,
                "goodsId": good_id,
                "kdtId": kdt_id,
                "pointsPrice": 0,
                "propertyIds": [],
                "skuId": sku,
                "usePoints": False
            }],
            "coupon": {},
            "useCustomerCardInfo": {
                "specified": False
            },
            "costPoints": {
                "kdtId": kdt_id,
                "usePointDeduction": False
            }
        },
        "newCouponProcess": True,
        "unavailableItems": [],
        "asyncOrder": False,
        "delivery": {
            "hasFreightInsurance": False,
            "address": add_dict[sid],
            "expressType": "express",
            "expressTypeChoice": 0
        },
        "cloudOrderExt": {
            "extension": {}
        },
        "bookKeyCloudExtension": {
            "umpExt": ""
        },
        "confirmTotalPrice": int(sku_map[sku]['price'] * b_num / 100),
        "extensions": {
            "IS_SELECTED_PRIOR_USE_PAY_WAY": "-1",
            "IS_OPTIMAL_SOLUTION": "true",
            "IS_SELECT_PRESENT": "0",
            "SELECTED_PRESENTS": "[]",
            "BIZ_ORDER_ATTRIBUTE": "{\"APP_VERSION\":\"7.0.8-2.87.8\"}"
        },
        "behaviorOrderInfo": {
            "bizType": 158,
            "token": captcha_map[sid]
        }
    }
    try:
        r = requests.post(url=cop_url, headers=headers, data=json.dumps(data))
        r = r.json()
        if r['code'] == 0:
            order_no = r['data']['orderNo']
            print(
                f'下单成功||姓名:{add_dict[sid]["userName"]}||订单号:{order_no}||{datetime.datetime.now()}')
            sid_list.remove(sid)
        elif re.search('限购', str(r["msg"])):
            sid_list.remove(sid)
            print(f'{add_dict[sid]["userName"]} 已限购', datetime.datetime.now())
        else:
            print(f'{add_dict[sid]["userName"]}===>{r["msg"]}',
                  datetime.datetime.now())
        if re.search('下架', str(r["msg"])):
            print('已下架,退出')
            exit()
    except Exception as e:
        print(e)
        sid_list.remove(sid)
    buy_time[sid] += 1

# 1.定时模式：如果商品只有一个sku，自动选择；有多个，手动选择；2.监控模式：随机选择sku


def sku_choose():
    global choose_sku
    if mode == 1:
        sku_list = [{'skuid': _, 'detail': sku_map[_]} for _ in sku_map]
        for n, d in enumerate(sku_list):
            print(f'{n + 1}.', d)
        if len(sku_list) > 1:
            choose_num = int(input('选择第几个商品?==>')) - 1
            choose_sku = sku_list[choose_num]['skuid']
        else:
            choose_sku = sku_list[0]['skuid']
    else:
        choose_sku = random.choice(available_sku)
    print(f'选择:{sku_map[choose_sku]}\n')

# 打开多线程下单


def start_threads():
    threads = []
    for sid in sid_list:
        thread = threading.Thread(target=create_order, args=[sid, choose_sku])
        threads.append(thread)
    for thread in threads:
        thread.start()
        thread.join()
    zero_fill()

# 倒计时模式


def count():
    global y
    y = False
    x = True
    while x:
        now = time.time()
        ddl = sold_time / 1000 - now
        if ddl <= 0.8:
            start_threads()
            x = False

# 监控模式


def monitor():
    global available_sku
    while sid_list:
        available_sku = []
        read_captcha()
        get_detail()
        if captcha_map[sid_list[0]] != '0':
            if all_stock > 0:
                condition = True  # 这里可加筛选条件
                available_sku = [_ for _ in sku_map if (
                    sku_map[_]['stock'] > 0 & condition)]
                sku_stock = {_: sku_map[_]['stock']
                             for _ in sku_map if sku_map[_]['stock'] > 0}
                if available_sku:
                    print(f'补货:{sku_stock}--{datetime.datetime.now()}\n')
                else:
                    print(f'无匹配目标,有库存:{sku_stock}', datetime.datetime.now())
            else:
                print('无库存,继续监控', datetime.datetime.now())
        else:
            print('等待验证码中......')
        if available_sku:
            sku_choose()
            start_threads()
        for _ in buy_time:
            if buy_time[_] >= 4:
                sid_list.remove(_)
        time.sleep(0.8)


if __name__ == '__main__':

    read_captcha()

    sid_list = encrypt.sid_list  # 从encrypt文件中读取用户列表
    for s in sid_list:
        buy_time[s] = 0

    print('------有赞V2模式------\n')
    t = 0
    aim_url = encrypt.aim_url
    alias = re.findall(r'alias=(.*?)&', aim_url)[0]
    cop_url = f'https://cashier.youzan.com/pay/wsctrade/order/buy/v2/bill-fast.json?kdt_id={kdt_id}'
    b_num = 1  # 控制购买数量
    # get_proxy()
    get_detail()
    get_address()
    if add_dict:
        if sold_time / 1000 <= time.time():
            mode = 0
            print('------捡漏模式------\n')
            monitor()
        else:
            mode = 1
            print(
                f"开售时间:{time.strftime('%H:%M:%S', time.localtime(sold_time / 1000))}")
            print('------倒计时模式------\n')
            sku_choose()
            cap_time = time.strftime(
                '%H:%M:%S', time.localtime(sold_time / 1000 - 5))
            pre_time = time.strftime(
                '%H:%M:%S', time.localtime(sold_time / 1000 - 3))
            schedule.every().day.at(cap_time).do(read_captcha)
            schedule.every().day.at(pre_time).do(count)
            while y:
                schedule.run_pending()
                print('倒计时 %s sec' % int(sold_time / 1000 - time.time()))
                time.sleep(1)
    else:
        exit()
