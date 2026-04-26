import ccxt
import ccxt.async_support as ccxt_async
import asyncio
import time
import json

FUNDING_EXCHANGES = ['binance', 'bybit', 'okx', 'bitget', 'gateio', 'mexc', 'htx']


async def fetch_funding_rates(exchange_id):
    exchange = None
    try:
        exchange_class = getattr(ccxt_async, exchange_id)
        exchange = exchange_class({'enableRateLimit': True, 'timeout': 15000})
        await exchange.load_markets()

        futures_markets = [s for s, m in exchange.markets.items()
                          if m.get('swap') and m.get('linear') and '/USDT' in s]

        rates = {}
        try:
            all_rates = await exchange.fetch_funding_rates()
            for symbol, info in all_rates.items():
                if '/USDT' in symbol and ':' in symbol:
                    base = symbol.split('/')[0]
                    rate = info.get('fundingRate')
                    next_time = info.get('fundingTimestamp') or info.get('nextFundingTimestamp')
                    if rate is not None:
                        rates[base] = {
                            'symbol': symbol,
                            'rate': rate,
                            'annualized': rate * 3 * 365 * 100,
                            'next_funding': next_time,
                        }
        except Exception:
            for symbol in futures_markets[:50]:
                try:
                    info = await exchange.fetch_funding_rate(symbol)
                    base = symbol.split('/')[0]
                    rate = info.get('fundingRate')
                    if rate is not None:
                        rates[base] = {
                            'symbol': symbol,
                            'rate': rate,
                            'annualized': rate * 3 * 365 * 100,
                            'next_funding': info.get('fundingTimestamp'),
                        }
                except:
                    pass

        await exchange.close()
        return exchange_id, rates
    except Exception as e:
        if exchange:
            try:
                await exchange.close()
            except:
                pass
        return exchange_id, {}


async def scan_funding():
    results = {}
    tasks = [fetch_funding_rates(eid) for eid in FUNDING_EXCHANGES]

    for coro in asyncio.as_completed(tasks):
        eid, rates = await coro
        if rates:
            results[eid] = rates

    opportunities = []

    all_coins = set()
    for eid, rates in results.items():
        all_coins.update(rates.keys())

    for coin in all_coins:
        exchange_rates = []
        for eid, rates in results.items():
            if coin in rates:
                exchange_rates.append({
                    'exchange': eid,
                    **rates[coin]
                })

        if not exchange_rates:
            continue

        exchange_rates.sort(key=lambda x: x['rate'], reverse=True)
        highest = exchange_rates[0]

        if highest['rate'] > 0.0001:
            daily_pct = highest['rate'] * 3 * 100
            annual_pct = highest['annualized']

            on_5k = 5000 * highest['rate'] * 3
            on_5k_monthly = on_5k * 30

            opportunities.append({
                'coin': coin,
                'exchange': highest['exchange'],
                'symbol': highest['symbol'],
                'funding_rate': round(highest['rate'] * 100, 4),
                'daily_pct': round(daily_pct, 4),
                'annual_pct': round(annual_pct, 2),
                'daily_5k': round(on_5k, 2),
                'monthly_5k': round(on_5k_monthly, 2),
                'all_exchanges': exchange_rates,
                'num_exchanges': len(exchange_rates),
            })

    opportunities.sort(key=lambda x: x['funding_rate'], reverse=True)
    return opportunities


def run_funding_scan():
    return asyncio.run(scan_funding())


if __name__ == '__main__':
    from rich.console import Console
    from rich.table import Table

    console = Console()
    console.print("[bold cyan]Scanning funding rates...[/bold cyan]")

    start = time.time()
    opps = run_funding_scan()
    elapsed = time.time() - start

    table = Table(title=f"Funding Rate Opportunities ({len(opps)} coins, {elapsed:.1f}s)")
    table.add_column("#", width=4)
    table.add_column("Coin", style="cyan", width=8)
    table.add_column("Exchange", width=10)
    table.add_column("Rate/8h", justify="right", width=10)
    table.add_column("Daily %", justify="right", width=10)
    table.add_column("Annual %", justify="right", width=10)
    table.add_column("$/day on $5K", justify="right", style="green", width=12)
    table.add_column("$/month on $5K", justify="right", style="bold green", width=14)

    for i, o in enumerate(opps[:30], 1):
        table.add_row(
            str(i), o['coin'], o['exchange'],
            f"{o['funding_rate']}%", f"{o['daily_pct']}%", f"{o['annual_pct']}%",
            f"${o['daily_5k']}", f"${o['monthly_5k']}"
        )

    console.print(table)
