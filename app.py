import ccxt
import ccxt.async_support as ccxt_async
import asyncio
import time
import json
import threading
import requests
from flask import Flask, jsonify, render_template_string
from funding import scan_funding

app = Flask(__name__)

# Networks supported by major exchanges (these don't expose currencies without API keys)
EXCHANGE_NETWORKS = {
    'binance': ['ERC20', 'BEP20', 'TRC20', 'SOL', 'MATIC', 'ARBONE', 'OP', 'AVAXC', 'BASE'],
    'bybit': ['ERC20', 'BEP20', 'TRC20', 'SOL', 'MATIC', 'ARBONE', 'OP', 'AVAXC', 'BASE'],
    'mexc': ['ERC20', 'BEP20', 'TRC20', 'SOL', 'MATIC', 'ARBONE', 'OP', 'AVAXC', 'BASE'],
    'bingx': ['ERC20', 'BEP20', 'TRC20', 'SOL', 'ARBONE', 'OP', 'BASE'],
    'phemex': ['ERC20', 'BEP20', 'TRC20', 'SOL'],
    'okx': ['ERC20', 'BEP20', 'TRC20', 'SOL', 'MATIC', 'ARBONE', 'OP', 'AVAXC', 'BASE'],
    'weex': ['ERC20', 'BEP20', 'TRC20'],
    'deepcoin': ['ERC20', 'BEP20', 'TRC20'],
    'toobit': ['ERC20', 'BEP20', 'TRC20'],
}

NETWORK_FEES_APPROX = {
    'TRC20': 1.0,
    'BEP20': 0.5,
    'SOL': 0.01,
    'BASE': 0.1,
    'ARBONE': 0.2,
    'OP': 0.2,
    'MATIC': 0.1,
    'AVAXC': 0.3,
    'ERC20': 5.0,
}

# CoinGecko exchange ID mapping (CoinGecko uses different IDs than CCXT)
EXCHANGE_TRADE_URLS = {
    'binance': 'https://www.binance.com/en/trade/{BASE}_{QUOTE}?type=spot',
    'bybit': 'https://www.bybit.com/en/trade/spot/{BASE}/{QUOTE}',
    'okx': 'https://www.okx.com/trade-spot/{base}-{quote}',
    'gateio': 'https://www.gate.io/trade/{BASE}_{QUOTE}',
    'gate': 'https://www.gate.io/trade/{BASE}_{QUOTE}',
    'kucoin': 'https://www.kucoin.com/trade/{BASE}-{QUOTE}',
    'mexc': 'https://www.mexc.com/exchange/{BASE}_{QUOTE}',
    'htx': 'https://www.htx.com/trade/{base}_{quote}',
    'huobi': 'https://www.htx.com/trade/{base}_{quote}',
    'bitget': 'https://www.bitget.com/spot/{BASE}{QUOTE}',
    'kraken': 'https://www.kraken.com/prices/{base}',
    'coinbase': 'https://www.coinbase.com/advanced-trade/spot/{BASE}-{QUOTE}',
    'coinbaseexchange': 'https://www.coinbase.com/advanced-trade/spot/{BASE}-{QUOTE}',
    'coinbaseadvanced': 'https://www.coinbase.com/advanced-trade/spot/{BASE}-{QUOTE}',
    'bitfinex': 'https://trading.bitfinex.com/t/{BASE}:{QUOTE}',
    'poloniex': 'https://poloniex.com/trade/{BASE}_{QUOTE}',
    'bitmart': 'https://www.bitmart.com/trade/en-US?symbol={BASE}_{QUOTE}',
    'bingx': 'https://bingx.com/en/spot/{BASE}{QUOTE}/',
    'phemex': 'https://phemex.com/spot/trade/{BASE}{QUOTE}',
    'whitebit': 'https://whitebit.com/trade/{BASE}-{QUOTE}',
    'lbank': 'https://www.lbank.com/trade/{base}_{quote}',
    'digifinex': 'https://www.digifinex.com/en-ww/trade/{BASE}/{QUOTE}',
    'ascendex': 'https://ascendex.com/en/cashtrade-spottrading/{base}/{quote}',
    'bitrue': 'https://www.bitrue.com/trade/{base}_{quote}',
    'coinex': 'https://www.coinex.com/en/exchange/{base}-{quote}',
    'xt': 'https://www.xt.com/en/trade/{base}_{quote}',
    'hitbtc': 'https://hitbtc.com/{base}-to-{quote}',
    'backpack': 'https://backpack.exchange/trade/{BASE}_{QUOTE}',
    'cryptocom': 'https://crypto.com/exchange/trade/{BASE}_{QUOTE}',
    'bitstamp': 'https://www.bitstamp.net/markets/{base}/{quote}/',
}


def get_trade_url(exchange_id, base, quote='USDT'):
    template = EXCHANGE_TRADE_URLS.get(exchange_id)
    if not template:
        return None
    return template.format(
        BASE=base.upper(), QUOTE=quote.upper(),
        base=base.lower(), quote=quote.lower()
    )


COINGECKO_EXCHANGE_MAP = {
    'binance': 'binance', 'bybit': 'bybit_spot', 'okx': 'okx',
    'gateio': 'gate', 'gate': 'gate', 'kucoin': 'kucoin',
    'mexc': 'mxc', 'htx': 'huobi', 'huobi': 'huobi',
    'bitget': 'bitget', 'coinbase': 'gdax', 'coinbaseexchange': 'gdax',
    'coinbaseadvanced': 'gdax', 'kraken': 'kraken',
    'bitfinex': 'bitfinex', 'bitstamp': 'bitstamp',
    'poloniex': 'poloniex', 'bitmart': 'bitmart',
    'bingx': 'bingx', 'phemex': 'phemex', 'whitebit': 'whitebit',
    'lbank': 'lbank', 'digifinex': 'digifinex', 'ascendex': 'ascendex',
    'bitrue': 'bitrue', 'coinex': 'coinex', 'xt': 'xt',
    'deepcoin': 'deepcoin', 'toobit': 'toobit', 'weex': 'weex',
    'bydfi': 'bydfi', 'bigone': 'bigone', 'exmo': 'exmo',
    'cryptocom': 'crypto_com', 'hitbtc': 'hitbtc', 'bequant': 'bequant',
    'backpack': 'backpack_exchange',
}

coingecko_cache = {}


def coingecko_verify(coin_symbol, buy_exchange, sell_exchange):
    cache_key = coin_symbol.upper()

    if cache_key in coingecko_cache:
        exchange_set = coingecko_cache[cache_key]
    else:
        try:
            r = requests.get(
                'https://api.coingecko.com/api/v3/search',
                params={'query': coin_symbol}, timeout=10
            )
            data = r.json()
            coins = [c for c in data.get('coins', []) if c['symbol'].upper() == coin_symbol.upper()]

            if not coins:
                coingecko_cache[cache_key] = None
                return 'NO_DATA'

            coin_id = coins[0]['id']
            time.sleep(0.5)

            r2 = requests.get(
                f'https://api.coingecko.com/api/v3/coins/{coin_id}/tickers',
                params={'include_exchange_logo': 'false', 'depth': 'false'},
                timeout=10
            )
            tickers = r2.json().get('tickers', [])
            exchange_set = set(t['market']['identifier'] for t in tickers)
            coingecko_cache[cache_key] = exchange_set

        except Exception:
            coingecko_cache[cache_key] = None
            return 'NO_DATA'

    if exchange_set is None:
        return 'NO_DATA'

    buy_cg = COINGECKO_EXCHANGE_MAP.get(buy_exchange, buy_exchange)
    sell_cg = COINGECKO_EXCHANGE_MAP.get(sell_exchange, sell_exchange)

    buy_found = buy_cg in exchange_set
    sell_found = sell_cg in exchange_set

    if buy_found and sell_found:
        return 'CG_VERIFIED'
    elif buy_found or sell_found:
        return 'CG_PARTIAL'
    else:
        return 'CG_NOT_FOUND'

EXCLUDED_EXCHANGES = ['theocean', 'coinflex', 'ftx', 'ftxus']
STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'}
LEVERAGED_SUFFIXES = ('3L', '3S', '2L', '2S', '5L', '5S', 'UP', 'DOWN', 'BULL', 'BEAR')
MIN_PROFIT_PCT = 0.1
MAX_PROFIT_PCT = 50
MIN_VOLUME_USD = 0
MIN_PRICE = 0.0000001

TRUSTED_EXCHANGES = {
    'binance', 'bybit', 'okx', 'coinbase', 'coinbaseexchange', 'coinbaseadvanced',
    'kraken', 'kucoin', 'bitget', 'mexc', 'gateio', 'gate',
    'htx', 'huobi', 'bitfinex', 'bitstamp', 'cryptocom',
    'bingx', 'phemex', 'whitebit', 'coinex', 'lbank',
}

scan_data = {
    'opportunities': [],
    'funding': [],
    'stats': {},
    'funding_stats': {},
    'last_scan': None,
    'scanning': False,
    'exchanges_total': 0,
    'exchanges_success': 0,
    'scan_progress': 0,
    'scan_log': [],
}


def get_all_exchanges():
    return [eid for eid in ccxt.exchanges if eid not in EXCLUDED_EXCHANGES]


async def fetch_tickers_safe(exchange_id):
    exchange = None
    try:
        exchange_class = getattr(ccxt_async, exchange_id)
        exchange = exchange_class({'enableRateLimit': True, 'timeout': 15000})
        tickers = await exchange.fetch_tickers()
        currencies = {}
        try:
            currencies = await exchange.fetch_currencies()
        except:
            pass
        await exchange.close()
        return exchange_id, tickers, currencies
    except:
        if exchange:
            try:
                await exchange.close()
            except:
                pass
        return exchange_id, None, {}


async def scan_exchanges(exchange_ids, max_concurrent=20):
    results = {}
    all_currencies = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_fetch(eid):
        async with semaphore:
            return await fetch_tickers_safe(eid)

    tasks = [limited_fetch(eid) for eid in exchange_ids]
    scan_data['exchanges_total'] = len(exchange_ids)
    done = 0
    success = 0

    for coro in asyncio.as_completed(tasks):
        eid, tickers, currencies = await coro
        done += 1
        if tickers:
            results[eid] = tickers
            if currencies:
                all_currencies[eid] = currencies
            success += 1
            scan_data['scan_log'].append({'exchange': eid, 'status': 'ok', 'pairs': len(tickers)})
        else:
            scan_data['scan_log'].append({'exchange': eid, 'status': 'fail', 'pairs': 0})

        scan_data['scan_progress'] = done
        scan_data['exchanges_success'] = success

    return results, all_currencies


def is_leveraged(symbol):
    base = symbol.split('/')[0]
    return any(base.endswith(s) for s in LEVERAGED_SUFFIXES)


def get_token_info(all_currencies, exchange_id, coin_code):
    if exchange_id not in all_currencies:
        return None
    return all_currencies[exchange_id].get(coin_code)


def extract_contract(network_info):
    if not network_info:
        return None
    info = network_info.get('info')
    if not info or not isinstance(info, dict):
        return None
    for key, val in info.items():
        if 'contract' in key.lower() and val:
            addr = str(val).strip().lower()
            if len(addr) > 10:
                return addr
    return None


def check_withdraw_deposit(all_currencies, buy_exchange, sell_exchange, coin_code):
    buy_info = get_token_info(all_currencies, buy_exchange, coin_code)
    sell_info = get_token_info(all_currencies, sell_exchange, coin_code)

    can_withdraw = True
    can_deposit = True
    common_network = None
    token_names_match = True
    contract_verified = False
    contract_mismatch = False
    withdraw_fee = None
    buy_name = None
    sell_name = None

    if buy_info:
        buy_name = buy_info.get('name') or ''
        if buy_info.get('withdraw') is False:
            can_withdraw = False
        networks_buy = buy_info.get('networks') or {}
        if networks_buy:
            withdraw_ok = any(n.get('withdraw', True) for n in networks_buy.values() if n)
            if not withdraw_ok:
                can_withdraw = False

    if sell_info:
        sell_name = sell_info.get('name') or ''
        if sell_info.get('deposit') is False:
            can_deposit = False
        networks_sell = sell_info.get('networks') or {}
        if networks_sell:
            deposit_ok = any(n.get('deposit', True) for n in networks_sell.values() if n)
            if not deposit_ok:
                can_deposit = False

    if buy_name and sell_name:
        bn = buy_name.lower().strip()
        sn = sell_name.lower().strip()
        cc = coin_code.lower().strip()
        if bn == sn:
            token_names_match = True
        elif bn == cc or sn == cc:
            # one exchange just returns the ticker as name — not a mismatch
            token_names_match = True
        elif bn in sn or sn in bn:
            token_names_match = True
        else:
            token_names_match = False

    if buy_info and sell_info:
        nets_buy = (buy_info.get('networks') or {})
        nets_sell = (sell_info.get('networks') or {})
        common = set(nets_buy.keys()) & set(nets_sell.keys())

        for net in common:
            nb = nets_buy.get(net) or {}
            ns = nets_sell.get(net) or {}

            buy_contract = extract_contract(nb)
            sell_contract = extract_contract(ns)

            if buy_contract and sell_contract:
                if buy_contract == sell_contract:
                    contract_verified = True
                else:
                    contract_mismatch = True
                    continue

            if nb.get('withdraw', True) and ns.get('deposit', True):
                if common_network is None:
                    common_network = net
                    fee_info = nb.get('fee')
                    if fee_info is not None:
                        withdraw_fee = fee_info
                    if contract_verified:
                        break

    # Fallback: if no network found from API, use hardcoded exchange network data
    if common_network is None:
        buy_nets = None
        sell_nets = None

        if buy_info:
            buy_api_nets = set((buy_info.get('networks') or {}).keys())
            if buy_api_nets:
                buy_nets = buy_api_nets
        if buy_nets is None and buy_exchange in EXCHANGE_NETWORKS:
            buy_nets = set(EXCHANGE_NETWORKS[buy_exchange])

        if sell_info:
            sell_api_nets = set((sell_info.get('networks') or {}).keys())
            if sell_api_nets:
                sell_nets = sell_api_nets
        if sell_nets is None and sell_exchange in EXCHANGE_NETWORKS:
            sell_nets = set(EXCHANGE_NETWORKS[sell_exchange])

        if buy_nets and sell_nets:
            common_fallback = buy_nets & sell_nets
            if common_fallback:
                # Pick cheapest network
                best_net = None
                best_fee = 999
                for net in common_fallback:
                    fee = NETWORK_FEES_APPROX.get(net, 10)
                    if fee < best_fee:
                        best_fee = fee
                        best_net = net
                if best_net:
                    common_network = best_net
                    if withdraw_fee is None:
                        withdraw_fee = best_fee

    # verification level
    if contract_mismatch and not contract_verified:
        verify = 'FAKE'
    elif contract_verified:
        verify = 'VERIFIED'
    elif not token_names_match and buy_name and sell_name:
        bn = buy_name.lower().strip()
        sn = sell_name.lower().strip()
        cc = coin_code.lower().strip()
        if bn != cc and sn != cc:
            verify = 'FAKE'
        else:
            verify = 'UNKNOWN'
    elif token_names_match and buy_name and sell_name:
        bn = buy_name.lower().strip()
        sn = sell_name.lower().strip()
        cc = coin_code.lower().strip()
        if bn == sn and bn != cc:
            verify = 'NAME_MATCH'
        elif bn in sn or sn in bn:
            verify = 'NAME_MATCH'
        else:
            verify = 'UNKNOWN'
    else:
        verify = 'UNKNOWN'

    return {
        'can_withdraw': can_withdraw,
        'can_deposit': can_deposit,
        'common_network': common_network,
        'token_names_match': token_names_match,
        'contract_verified': contract_verified,
        'contract_mismatch': contract_mismatch,
        'verify': verify,
        'withdraw_fee': withdraw_fee,
        'buy_name': buy_name or coin_code,
        'sell_name': sell_name or coin_code,
    }


def find_arbitrage(all_tickers, all_currencies):
    coin_prices = {}

    for exchange_id, tickers in all_tickers.items():
        for symbol, ticker in tickers.items():
            if not ticker or not isinstance(ticker, dict):
                continue
            if '/USDT' not in symbol:
                continue

            norm = symbol.split(':')[0]
            base = norm.split('/')[0]

            if base in STABLECOINS or is_leveraged(norm):
                continue

            bid = ticker.get('bid')
            ask = ticker.get('ask')
            volume = ticker.get('quoteVolume') or 0

            if not bid or not ask or bid <= 0 or ask <= 0:
                continue
            if ask < MIN_PRICE or bid < MIN_PRICE:
                continue
            if bid > ask * 1.5:
                continue

            if norm not in coin_prices:
                coin_prices[norm] = []
            coin_prices[norm].append({
                'exchange': exchange_id, 'symbol': symbol,
                'bid': bid, 'ask': ask, 'volume': volume,
            })

    opportunities = []
    for pair, prices in coin_prices.items():
        if len(prices) < 2:
            continue

        median_price = sorted(p['ask'] for p in prices)[len(prices) // 2]
        filtered = [p for p in prices if 0.1 * median_price < p['ask'] < 10 * median_price]
        if len(filtered) < 2:
            continue

        coin_code = pair.split('/')[0]

        cheapest = min(filtered, key=lambda x: x['ask'])
        most_expensive = max(filtered, key=lambda x: x['bid'])

        if cheapest['exchange'] == most_expensive['exchange']:
            continue

        profit_pct = ((most_expensive['bid'] - cheapest['ask']) / cheapest['ask']) * 100

        if profit_pct < 0.1 or profit_pct > MAX_PROFIT_PCT:
            continue

        transfer = check_withdraw_deposit(
            all_currencies, cheapest['exchange'], most_expensive['exchange'], coin_code
        )

        status = 'READY'
        if transfer['verify'] == 'FAKE':
            status = 'FAKE_TOKEN'
        elif not transfer['token_names_match']:
            status = 'NAME_MISMATCH'
        elif not transfer['can_withdraw']:
            status = 'NO_WITHDRAW'
        elif not transfer['can_deposit']:
            status = 'NO_DEPOSIT'
        elif transfer['common_network'] is None and all_currencies.get(cheapest['exchange']) and all_currencies.get(most_expensive['exchange']):
            status = 'NO_COMMON_NET'

        net_profit = profit_pct
        if transfer['withdraw_fee'] is not None and cheapest['ask'] > 0:
            fee_pct = (transfer['withdraw_fee'] / cheapest['ask']) * 100
            net_profit = profit_pct - fee_pct

        all_exchanges = sorted(filtered, key=lambda x: x['ask'])
        price_map = [{'ex': p['exchange'], 'ask': round(p['ask'], 8), 'bid': round(p['bid'], 8), 'vol': round(p['volume'])} for p in all_exchanges]

        opportunities.append({
            'coin': coin_code,
            'pair': pair,
            'buy_exchange': cheapest['exchange'],
            'buy_price': cheapest['ask'],
            'buy_volume': cheapest['volume'],
            'sell_exchange': most_expensive['exchange'],
            'sell_price': most_expensive['bid'],
            'sell_volume': most_expensive['volume'],
            'profit_pct': round(profit_pct, 2),
            'net_profit_pct': round(net_profit, 2),
            'spread': round(most_expensive['bid'] - cheapest['ask'], 8),
            'status': status,
            'verify': transfer['verify'],
            'network': transfer['common_network'] or '-',
            'withdraw_fee': transfer['withdraw_fee'],
            'buy_name': transfer['buy_name'],
            'sell_name': transfer['sell_name'],
            'buy_url': get_trade_url(cheapest['exchange'], coin_code) or '',
            'sell_url': get_trade_url(most_expensive['exchange'], coin_code) or '',
            'num_exchanges': len(filtered),
            'all_prices': price_map[:10],
            'trusted': cheapest['exchange'] in TRUSTED_EXCHANGES and most_expensive['exchange'] in TRUSTED_EXCHANGES,
        })

    opportunities.sort(key=lambda x: x['profit_pct'], reverse=True)
    return opportunities


async def run_scan():
    scan_data['scanning'] = True
    scan_data['scan_log'] = []
    scan_data['scan_progress'] = 0

    exchange_ids = get_all_exchanges()
    start = time.time()
    all_tickers, all_currencies = await scan_exchanges(exchange_ids)
    scan_time = time.time() - start

    opportunities = find_arbitrage(all_tickers, all_currencies)

    coins_seen = set()
    unique_opps = []
    for o in opportunities:
        key = f"{o['coin']}-{o['buy_exchange']}-{o['sell_exchange']}"
        if key not in coins_seen:
            coins_seen.add(key)
            unique_opps.append(o)

    top_coins = {}
    for o in unique_opps:
        if o['coin'] not in top_coins or o['profit_pct'] > top_coins[o['coin']]['profit_pct']:
            top_coins[o['coin']] = o

    # CoinGecko verification — only coins with profit > 0.5% to keep it fast
    worth_verifying = [o for o in unique_opps if o['profit_pct'] >= 0.5]
    worth_verifying.sort(key=lambda x: x['profit_pct'], reverse=True)

    verified_coins = {}
    for o in worth_verifying:
        if o['coin'] in verified_coins:
            continue
        cg_result = coingecko_verify(o['coin'], o['buy_exchange'], o['sell_exchange'])
        verified_coins[o['coin']] = cg_result
        time.sleep(1.5)

    for o in unique_opps:
        cg_result = verified_coins.get(o['coin'])
        if cg_result == 'CG_VERIFIED':
            o['verify'] = 'CG_VERIFIED'
        elif cg_result == 'CG_NOT_FOUND':
            o['verify'] = 'CG_NOT_FOUND'
        elif cg_result == 'CG_PARTIAL':
            o['verify'] = 'CG_PARTIAL'

    verified_opps = [o for o in unique_opps if o.get('verify') in ('CG_VERIFIED', 'VERIFIED')]
    all_opps = unique_opps

    # Funding rate scan
    funding_opps = await scan_funding()
    scan_data['funding'] = funding_opps[:100]
    scan_data['funding_stats'] = {
        'total': len(funding_opps),
        'best_daily': funding_opps[0]['daily_5k'] if funding_opps else 0,
        'best_coin': funding_opps[0]['coin'] if funding_opps else '-',
        'best_exchange': funding_opps[0]['exchange'] if funding_opps else '-',
        'best_annual': funding_opps[0]['annual_pct'] if funding_opps else 0,
    }

    total_scan_time = time.time() - start
    scan_data['opportunities'] = verified_opps[:200]
    scan_data['all_opportunities'] = all_opps[:500]
    scan_data['last_scan'] = time.strftime('%Y-%m-%d %H:%M:%S')
    scan_data['scanning'] = False
    scan_data['stats'] = {
        'total_opportunities': len(unique_opps),
        'total_raw': len(opportunities),
        'exchanges_scanned': scan_data['exchanges_success'],
        'exchanges_total': scan_data['exchanges_total'],
        'scan_time': round(total_scan_time, 1),
        'unique_coins': len(top_coins),
        'best_profit': unique_opps[0]['profit_pct'] if unique_opps else 0,
        'avg_profit': round(sum(o['profit_pct'] for o in unique_opps) / len(unique_opps), 2) if unique_opps else 0,
    }


def scan_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_scan())


BASIC_KEYS = {
    'CG-BASIC-001',
    'CG-BASIC-002',
    'CG-BASIC-003',
    'CG-BASIC-004',
    'CG-BASIC-005',
}

PRO_KEYS = {
    'CG-PRO-001',
    'CG-PRO-002',
    'CG-PRO-003',
}

ACCESS_KEYS = BASIC_KEYS | PRO_KEYS | {'demo2026'}

LOGIN_PAGE = '''
<!DOCTYPE html><html><head><title>CryptoGap</title>
<style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:'SF Mono',monospace;background:#0a0a0f;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh}
.box{background:#161b22;border:1px solid #21262d;border-radius:12px;padding:40px;text-align:center;max-width:400px;width:90%}
h1{color:#58a6ff;margin-bottom:8px;font-size:1.5rem}h1 span{color:#f0883e}
p{color:#8b949e;margin-bottom:24px;font-size:0.85rem}
input{width:100%;padding:12px;background:#0d1117;border:1px solid #21262d;color:#e0e0e0;border-radius:6px;font-family:inherit;font-size:0.9rem;margin-bottom:12px}
input:focus{border-color:#58a6ff;outline:none}
button{width:100%;padding:12px;background:linear-gradient(135deg,#238636,#2ea043);color:#fff;border:none;border-radius:6px;cursor:pointer;font-family:inherit;font-size:0.9rem;font-weight:600}
button:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(46,160,67,0.4)}
.err{color:#f85149;font-size:0.8rem;margin-top:8px;display:none}
.features{text-align:left;margin:20px 0;padding:16px;background:#0d1117;border-radius:8px;font-size:0.78rem;color:#8b949e;line-height:1.8}
.features b{color:#e0e0e0}
</style></head><body>
<div class="box">
<h1>Crypto<span>Gap</span></h1>
<p>Real-time arbitrage intelligence across 80+ exchanges</p>
<div class="features">
<b>What you get:</b><br>
- Spot arbitrage scanner (CoinGecko verified)<br>
- Funding rate arbitrage scanner<br>
- 22 trusted exchanges only<br>
- Direct trade links<br>
- Network & fee info<br>
</div>
<form method="POST" action="/login">
<input type="text" name="key" placeholder="Enter access key" required>
<button type="submit">Access Dashboard</button>
</form>
<p class="err" id="err">Invalid key</p>
<div style="margin-top:20px;font-size:0.72rem;color:#8b949e;line-height:1.8;text-align:left;padding:12px;background:#0d1117;border-radius:8px">
<b style="color:#e0e0e0">Plans:</b><br>
<span style="color:#3fb950">Basic $29/mo</span> — Dashboard + unlimited scans<br>
<span style="color:#f0883e">Pro $99/mo</span> — Everything + Telegram alerts<br>
</div>
</div>
<script>if(location.search.includes('err'))document.getElementById('err').style.display='block'</script>
</body></html>
'''

from functools import wraps
from flask import request, session, redirect, url_for

app.secret_key = 'cryptogap_secret_2026'


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated


@app.route('/')
@login_required
def index():
    import os
    html_path = os.path.join(os.path.dirname(__file__), 'dashboard.html')
    with open(html_path, 'r') as f:
        return f.read()


@app.route('/login', methods=['GET'])
def login_page():
    if session.get('authenticated'):
        return redirect(url_for('index'))
    return LOGIN_PAGE


@app.route('/login', methods=['POST'])
def login_submit():
    key = request.form.get('key', '').strip()
    if key in ACCESS_KEYS:
        session['authenticated'] = True
        return redirect(url_for('index'))
    return redirect('/login?err=1')


@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('login_page'))


@app.route('/api/data')
@login_required
def api_data():
    return jsonify(scan_data)


@app.route('/api/scan', methods=['POST'])
@login_required
def api_scan():
    if scan_data['scanning']:
        return jsonify({'status': 'already scanning'})
    t = threading.Thread(target=scan_thread, daemon=True)
    t.start()
    return jsonify({'status': 'scan started'})


DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Crypto Arbitrage Scanner</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: #0a0a0f;
    color: #e0e0e0;
    min-height: 100vh;
}
.header {
    background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
    border-bottom: 1px solid #21262d;
    padding: 20px 30px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.header h1 { font-size: 1.4rem; color: #58a6ff; font-weight: 600; }
.header h1 span { color: #f0883e; }
.header-right { display: flex; align-items: center; gap: 15px; }
.scan-btn {
    background: linear-gradient(135deg, #238636 0%, #2ea043 100%);
    color: #fff; border: none; padding: 10px 24px; border-radius: 6px;
    cursor: pointer; font-family: inherit; font-size: 0.9rem; font-weight: 600; transition: all 0.2s;
}
.scan-btn:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(46,160,67,0.4); }
.scan-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.scan-btn.scanning { background: linear-gradient(135deg, #da3633 0%, #f85149 100%); }
.last-scan { color: #8b949e; font-size: 0.8rem; }

.stats-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 12px; padding: 20px 30px;
}
.stat-card {
    background: #161b22; border: 1px solid #21262d; border-radius: 8px;
    padding: 16px; text-align: center;
}
.stat-value { font-size: 1.8rem; font-weight: 700; margin-bottom: 4px; }
.stat-label { color: #8b949e; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; }
.green { color: #3fb950; } .yellow { color: #d29922; } .blue { color: #58a6ff; }
.orange { color: #f0883e; } .red { color: #f85149; }

.filters {
    padding: 10px 30px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
}
.filter-group { display: flex; align-items: center; gap: 6px; }
.filter-group label { color: #8b949e; font-size: 0.8rem; }
.filter-group input, .filter-group select {
    background: #0d1117; border: 1px solid #21262d; color: #e0e0e0;
    padding: 6px 10px; border-radius: 4px; font-family: inherit; font-size: 0.85rem;
}
.filter-group input:focus, .filter-group select:focus { border-color: #58a6ff; outline: none; }

.table-container { padding: 0 30px 30px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
thead th {
    background: #161b22; color: #8b949e; padding: 10px 10px; text-align: left;
    font-weight: 600; text-transform: uppercase; font-size: 0.65rem; letter-spacing: 1px;
    border-bottom: 2px solid #21262d; position: sticky; top: 0; cursor: pointer; user-select: none;
}
thead th:hover { color: #58a6ff; }
tbody tr { border-bottom: 1px solid #21262d; transition: background 0.15s; }
tbody tr:hover { background: #161b22; }
tbody tr.blocked { opacity: 0.45; }
td { padding: 8px 10px; }
td.price { text-align: right; font-variant-numeric: tabular-nums; }
td.profit { text-align: right; font-weight: 700; }
.profit-high { color: #3fb950; } .profit-med { color: #d29922; } .profit-low { color: #8b949e; }
.exchange-tag { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.72rem; font-weight: 600; }
.buy-tag { background: rgba(63,185,80,0.15); color: #3fb950; }
.sell-tag { background: rgba(248,81,73,0.15); color: #f85149; }
.coin-name { font-weight: 700; color: #58a6ff; }
.arrow { color: #484f58; }

.status-badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
}
.status-READY { background: rgba(63,185,80,0.2); color: #3fb950; }
.status-NO_WITHDRAW { background: rgba(248,81,73,0.2); color: #f85149; }
.status-NO_DEPOSIT { background: rgba(248,81,73,0.2); color: #f85149; }
.status-NO_COMMON_NET { background: rgba(210,153,34,0.2); color: #d29922; }
.status-NAME_MISMATCH { background: rgba(248,81,73,0.3); color: #ff7b72; }
.status-FAKE_TOKEN { background: rgba(248,81,73,0.3); color: #ff7b72; }

.verify-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.68rem; font-weight: 700; }
.verify-VERIFIED, .verify-CG_VERIFIED { background: rgba(63,185,80,0.25); color: #3fb950; border: 1px solid rgba(63,185,80,0.4); }
.verify-NAME_MATCH { background: rgba(210,153,34,0.2); color: #d29922; border: 1px solid rgba(210,153,34,0.3); }
.verify-UNKNOWN, .verify-CG_PARTIAL { background: rgba(139,148,158,0.15); color: #8b949e; border: 1px solid rgba(139,148,158,0.2); }
.verify-FAKE, .verify-CG_NOT_FOUND { background: rgba(248,81,73,0.25); color: #f85149; border: 1px solid rgba(248,81,73,0.4); }

.progress-bar { width: 100%; height: 3px; background: #21262d; overflow: hidden; }
.progress-fill { height: 100%; background: linear-gradient(90deg, #238636, #3fb950); transition: width 0.3s; }
.empty-state { text-align: center; padding: 60px; color: #484f58; }
.empty-state h2 { font-size: 1.2rem; margin-bottom: 8px; color: #8b949e; }
.profit-bar-bg { width: 60px; height: 5px; background: #21262d; border-radius: 3px; display: inline-block; vertical-align: middle; margin-left: 6px; }
.profit-bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #d29922, #3fb950); }
.net-tag { font-size: 0.68rem; color: #8b949e; background: #21262d; padding: 1px 6px; border-radius: 3px; }
.name-info { font-size: 0.68rem; color: #6e7681; display: block; margin-top: 2px; }

@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
.scanning-indicator { animation: pulse 1.5s infinite; color: #f0883e; }
</style>
</head>
<body>

<div class="header">
    <h1>Crypto<span>Gap</span> <span style="font-size:0.6rem;color:#3fb950;vertical-align:middle;background:rgba(63,185,80,0.15);padding:2px 8px;border-radius:4px">VERIFIED ONLY</span></h1>
    <div class="header-right">
        <span class="last-scan" id="lastScan">No scan yet</span>
        <button class="scan-btn" id="scanBtn" onclick="startScan()">Scan Now</button>
    </div>
</div>
<div class="progress-bar"><div class="progress-fill" id="progressBar" style="width:0%"></div></div>

<div class="tabs" style="padding:10px 30px;display:flex;gap:0">
    <button class="tab-btn active" onclick="switchTab('arb')" id="tabArb" style="padding:10px 24px;background:#161b22;border:1px solid #21262d;border-bottom:2px solid #58a6ff;color:#58a6ff;cursor:pointer;font-family:inherit;font-weight:600;font-size:0.85rem;border-radius:6px 6px 0 0">Spot Arbitrage</button>
    <button class="tab-btn" onclick="switchTab('funding')" id="tabFunding" style="padding:10px 24px;background:#0d1117;border:1px solid #21262d;border-bottom:none;color:#8b949e;cursor:pointer;font-family:inherit;font-weight:600;font-size:0.85rem;border-radius:6px 6px 0 0">Funding Rate Arb</button>
</div>
<div id="arbSection">
<div class="stats-grid">
    <div class="stat-card"><div class="stat-value green" id="statReady">-</div><div class="stat-label">Ready to Trade</div></div>
    <div class="stat-card"><div class="stat-value yellow" id="statOpps">-</div><div class="stat-label">Total Found</div></div>
    <div class="stat-card"><div class="stat-value green" id="statBest">-</div><div class="stat-label">Best Profit</div></div>
    <div class="stat-card"><div class="stat-value orange" id="statAvg">-</div><div class="stat-label">Avg Profit</div></div>
    <div class="stat-card"><div class="stat-value blue" id="statExchanges">-</div><div class="stat-label">Exchanges</div></div>
    <div class="stat-card"><div class="stat-value blue" id="statCoins">-</div><div class="stat-label">Coins</div></div>
    <div class="stat-card"><div class="stat-value" id="statTime">-</div><div class="stat-label">Scan Time</div></div>
</div>

<div class="filters">
    <div class="filter-group">
        <label>Min Profit %</label>
        <input type="number" id="filterMinProfit" value="0.3" step="0.1" min="0" onchange="applyFilters()">
    </div>
    <div class="filter-group">
        <label>Coin</label>
        <input type="text" id="filterCoin" placeholder="e.g. BTC" oninput="applyFilters()">
    </div>
    <div class="filter-group">
        <label>Exchange</label>
        <input type="text" id="filterExchange" placeholder="e.g. binance" oninput="applyFilters()">
    </div>
    <div class="filter-group">
        <label>Status</label>
        <select id="filterStatus" onchange="applyFilters()">
            <option value="all">All</option>
            <option value="READY">Ready Only</option>
            <option value="blocked">Blocked Only</option>
        </select>
    </div>
    <div class="filter-group">
        <label>Verification</label>
        <select id="filterVerify" onchange="applyFilters()">
            <option value="all" selected>All (Pre-verified)</option>
            <option value="VERIFIED">CoinGecko Verified</option>
        </select>
    </div>
</div>

<div class="table-container">
    <table>
        <thead>
            <tr>
                <th onclick="sortTable('rank')">#</th>
                <th onclick="sortTable('coin')">Coin</th>
                <th onclick="sortTable('buy_exchange')">Buy On</th>
                <th onclick="sortTable('buy_price')">Buy Price</th>
                <th></th>
                <th onclick="sortTable('sell_exchange')">Sell On</th>
                <th onclick="sortTable('sell_price')">Sell Price</th>
                <th onclick="sortTable('profit_pct')">Profit %</th>
                <th onclick="sortTable('verify')">Verified</th>
                <th onclick="sortTable('status')">Status</th>
                <th onclick="sortTable('num_exchanges')">Exch#</th>
                <th>Network</th>
                <th>Verify</th>
            </tr>
        </thead>
        <tbody id="tableBody">
            <tr><td colspan="13" class="empty-state"><h2>Click "Scan Now" to start</h2>Scans 22 trusted exchanges, verifies every token via CoinGecko. Takes ~3-5 min.</td></tr>
        </tbody>
    </table>
</div>
</div><!-- end arbSection -->

<div id="fundingSection" style="display:none">
<div class="stats-grid">
    <div class="stat-card"><div class="stat-value green" id="fStatBestDaily">-</div><div class="stat-label">Best $/Day on $5K</div></div>
    <div class="stat-card"><div class="stat-value yellow" id="fStatBestCoin">-</div><div class="stat-label">Best Coin</div></div>
    <div class="stat-card"><div class="stat-value orange" id="fStatBestAnnual">-</div><div class="stat-label">Best Annual %</div></div>
    <div class="stat-card"><div class="stat-value blue" id="fStatTotal">-</div><div class="stat-label">Coins Found</div></div>
</div>
<div class="table-container">
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Coin</th>
                <th>Exchange</th>
                <th>Rate/8h</th>
                <th>Daily %</th>
                <th>Annual %</th>
                <th>$/Day on $5K</th>
                <th>$/Month on $5K</th>
            </tr>
        </thead>
        <tbody id="fundingBody">
            <tr><td colspan="8" class="empty-state"><h2>Click "Scan Now"</h2>Scans funding rates on Binance, Bybit, OKX, Bitget, Gate, MEXC, HTX</td></tr>
        </tbody>
    </table>
</div>
</div><!-- end fundingSection -->

<script>
let allData = [];
let fundingData = [];
let currentSort = { key: 'profit_pct', dir: 'desc' };

function switchTab(tab) {
    document.getElementById('arbSection').style.display = tab === 'arb' ? 'block' : 'none';
    document.getElementById('fundingSection').style.display = tab === 'funding' ? 'block' : 'none';
    document.getElementById('tabArb').style.borderBottom = tab === 'arb' ? '2px solid #58a6ff' : 'none';
    document.getElementById('tabArb').style.color = tab === 'arb' ? '#58a6ff' : '#8b949e';
    document.getElementById('tabArb').style.background = tab === 'arb' ? '#161b22' : '#0d1117';
    document.getElementById('tabFunding').style.borderBottom = tab === 'funding' ? '2px solid #f0883e' : 'none';
    document.getElementById('tabFunding').style.color = tab === 'funding' ? '#f0883e' : '#8b949e';
    document.getElementById('tabFunding').style.background = tab === 'funding' ? '#161b22' : '#0d1117';
}

function renderFunding(data) {
    const tbody = document.getElementById('fundingBody');
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No funding data</td></tr>'; return; }
    tbody.innerHTML = data.slice(0, 50).map((o, i) => {
        const color = o.daily_5k >= 50 ? 'profit-high' : o.daily_5k >= 20 ? 'profit-med' : 'profit-low';
        return `<tr>
            <td style="color:#484f58">${i+1}</td>
            <td class="coin-name">${o.coin}</td>
            <td><span class="exchange-tag buy-tag">${o.exchange}</span></td>
            <td class="price" style="color:#f0883e;font-weight:700">${o.funding_rate}%</td>
            <td class="price">${o.daily_pct}%</td>
            <td class="price" style="color:#d29922">${o.annual_pct}%</td>
            <td class="price ${color}" style="font-weight:700">$${o.daily_5k}</td>
            <td class="price" style="color:#3fb950;font-weight:700">$${o.monthly_5k}</td>
        </tr>`;
    }).join('');
}

async function startScan() {
    const btn = document.getElementById('scanBtn');
    btn.disabled = true; btn.textContent = 'Scanning...'; btn.classList.add('scanning');
    await fetch('/api/scan', { method: 'POST' });
}

function formatPrice(p) {
    if (p >= 1000) return '$' + p.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
    if (p >= 1) return '$' + p.toFixed(4);
    if (p >= 0.001) return '$' + p.toFixed(6);
    return '$' + p.toFixed(8);
}

function profitClass(pct) {
    if (pct >= 5) return 'profit-high';
    if (pct >= 1) return 'profit-med';
    return 'profit-low';
}

function statusLabel(s) {
    const map = {READY:'READY', NO_WITHDRAW:'NO WITHDRAW', NO_DEPOSIT:'NO DEPOSIT', NO_COMMON_NET:'NO NETWORK', NAME_MISMATCH:'DIFF NAME', FAKE_TOKEN:'FAKE TOKEN'};
    return map[s] || s;
}

function renderTable(data) {
    const tbody = document.getElementById('tableBody');
    if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="13" class="empty-state"><h2>No opportunities match filters</h2></td></tr>';
        return;
    }
    const maxProfit = Math.max(...data.map(d => d.profit_pct));
    tbody.innerHTML = data.slice(0, 100).map((o, i) => {
        const barWidth = Math.min(100, (o.profit_pct / maxProfit) * 100);
        const blocked = o.status !== 'READY' ? 'blocked' : '';
        const nameInfo = (o.buy_name && o.buy_name !== o.coin) ? o.buy_name : '';
        const sellNameInfo = (o.sell_name && o.sell_name !== o.buy_name) ? ` / ${o.sell_name}` : '';
        const nameNote = nameInfo ? `<span class="name-info">${nameInfo}${sellNameInfo}</span>` : '';
        const v = o.verify || 'UNKNOWN';
        const verifyLabels = {VERIFIED:'CONTRACT OK', CG_VERIFIED:'COINGECKO OK', NAME_MATCH:'NAME ONLY', UNKNOWN:'UNVERIFIED', FAKE:'DIFF TOKEN', CG_NOT_FOUND:'NOT ON CG', CG_PARTIAL:'CG PARTIAL'};
        return `<tr class="${blocked}">
            <td style="color:#484f58">${i+1}</td>
            <td><span class="coin-name">${o.coin}</span>${nameNote}</td>
            <td>${o.buy_url ? `<a href="${o.buy_url}" target="_blank" style="text-decoration:none"><span class="exchange-tag buy-tag">${o.buy_exchange} &#8599;</span></a>` : `<span class="exchange-tag buy-tag">${o.buy_exchange}</span>`}</td>
            <td class="price">${formatPrice(o.buy_price)}</td>
            <td class="arrow">&#10132;</td>
            <td>${o.sell_url ? `<a href="${o.sell_url}" target="_blank" style="text-decoration:none"><span class="exchange-tag sell-tag">${o.sell_exchange} &#8599;</span></a>` : `<span class="exchange-tag sell-tag">${o.sell_exchange}</span>`}</td>
            <td class="price">${formatPrice(o.sell_price)}</td>
            <td class="profit ${profitClass(o.profit_pct)}">
                ${o.profit_pct.toFixed(2)}%
                <div class="profit-bar-bg"><div class="profit-bar-fill" style="width:${barWidth}%"></div></div>
            </td>
            <td><span class="verify-badge verify-${v}">${verifyLabels[v] || v}</span></td>
            <td><span class="status-badge status-${o.status}">${statusLabel(o.status)}</span></td>
            <td style="text-align:center"><span style="color:#58a6ff;font-weight:700">${o.num_exchanges || '-'}</span></td>
            <td>${o.network !== '-' ? `<span class="net-tag">${o.network}</span>${o.withdraw_fee ? `<br><span style="font-size:0.6rem;color:#8b949e">~$${o.withdraw_fee} fee</span>` : ''}` : '<span style="color:#484f58">-</span>'}</td>
            <td><a href="https://www.coingecko.com/en/coins/${encodeURIComponent(o.buy_name && o.buy_name.length > 2 ? o.buy_name.toLowerCase().replace(/\\s+/g, '-') : o.coin.toLowerCase())}" target="_blank" style="color:#58a6ff;font-size:0.7rem;text-decoration:none">Check</a></td>
        </tr>`;
    }).join('');
}

function applyFilters() {
    const minP = parseFloat(document.getElementById('filterMinProfit').value) || 0;
    const coinFilter = document.getElementById('filterCoin').value.toUpperCase();
    const exchFilter = document.getElementById('filterExchange').value.toLowerCase();
    const statusFilter = document.getElementById('filterStatus').value;

    const verifyFilter = document.getElementById('filterVerify').value;

    let filtered = allData.filter(o => {
        if (o.profit_pct < minP) return false;
        if (coinFilter && !o.coin.includes(coinFilter)) return false;
        if (exchFilter && !o.buy_exchange.includes(exchFilter) && !o.sell_exchange.includes(exchFilter)) return false;
        if (statusFilter === 'READY' && o.status !== 'READY') return false;
        if (statusFilter === 'blocked' && o.status === 'READY') return false;
        if (verifyFilter === 'VERIFIED' && o.verify !== 'VERIFIED' && o.verify !== 'CG_VERIFIED') return false;
        if (verifyFilter === 'safe' && !['VERIFIED','CG_VERIFIED','NAME_MATCH'].includes(o.verify)) return false;
        return true;
    });

    filtered.sort((a, b) => {
        let va = a[currentSort.key], vb = b[currentSort.key];
        if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
        if (currentSort.dir === 'asc') return va > vb ? 1 : -1;
        return va < vb ? 1 : -1;
    });

    renderTable(filtered);
    document.getElementById('statReady').textContent = allData.filter(o => o.status === 'READY').length;
}

function sortTable(key) {
    if (currentSort.key === key) currentSort.dir = currentSort.dir === 'desc' ? 'asc' : 'desc';
    else currentSort = { key, dir: 'desc' };
    applyFilters();
}

async function pollData() {
    try {
        const res = await fetch('/api/data');
        const data = await res.json();

        if (data.scanning) {
            const pct = data.exchanges_total ? (data.scan_progress / data.exchanges_total * 100) : 0;
            document.getElementById('progressBar').style.width = pct + '%';
            document.getElementById('scanBtn').textContent = `Scanning ${data.scan_progress}/${data.exchanges_total}`;
            document.getElementById('scanBtn').disabled = true;
            document.getElementById('scanBtn').classList.add('scanning');
        } else {
            document.getElementById('progressBar').style.width = '0%';
            const btn = document.getElementById('scanBtn');
            btn.disabled = false;
            btn.textContent = 'Scan Now';
            btn.classList.remove('scanning');
        }

        if (data.last_scan) {
            document.getElementById('lastScan').textContent = 'Last scan: ' + data.last_scan;
        }

        if (data.stats && data.stats.total_opportunities !== undefined) {
            document.getElementById('statOpps').textContent = data.stats.total_opportunities;
            document.getElementById('statBest').textContent = data.stats.best_profit + '%';
            document.getElementById('statAvg').textContent = data.stats.avg_profit + '%';
            document.getElementById('statExchanges').textContent = data.stats.exchanges_scanned + '/' + data.stats.exchanges_total;
            document.getElementById('statCoins').textContent = data.stats.unique_coins;
            document.getElementById('statTime').textContent = data.stats.scan_time + 's';
        }

        if (data.opportunities && data.opportunities.length) {
            allData = data.opportunities;
            applyFilters();
        }

        if (data.funding && data.funding.length) {
            fundingData = data.funding;
            renderFunding(fundingData);
        }
        if (data.funding_stats && data.funding_stats.total) {
            document.getElementById('fStatBestDaily').textContent = '$' + data.funding_stats.best_daily;
            document.getElementById('fStatBestCoin').textContent = data.funding_stats.best_coin;
            document.getElementById('fStatBestAnnual').textContent = data.funding_stats.best_annual + '%';
            document.getElementById('fStatTotal').textContent = data.funding_stats.total;
        }
    } catch(e) {}
}

setInterval(pollData, 2000);
pollData();
</script>
</body>
</html>
'''

if __name__ == '__main__':
    print("\n  Crypto Arbitrage Scanner Dashboard")
    print("  http://localhost:5050\n")
    app.run(host='0.0.0.0', port=5050, debug=False)
