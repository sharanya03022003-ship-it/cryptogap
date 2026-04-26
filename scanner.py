import ccxt
import ccxt.async_support as ccxt_async
import asyncio
import time
import json
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

console = Console()

EXCLUDED_EXCHANGES = [
    'theocean', 'coinflex', 'ftx', 'ftxus',
]

STABLECOINS = {'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD'}

LEVERAGED_SUFFIXES = ('3L', '3S', '2L', '2S', '5L', '5S', 'UP', 'DOWN', 'BULL', 'BEAR')

MIN_PROFIT_PCT = 0.3
MAX_PROFIT_PCT = 50
MIN_VOLUME_USD = 50000
MIN_PRICE = 0.0000001


def get_all_exchanges():
    all_ids = ccxt.exchanges
    valid = []
    for eid in all_ids:
        if eid in EXCLUDED_EXCHANGES:
            continue
        valid.append(eid)
    return valid


async def fetch_tickers_safe(exchange_id):
    exchange = None
    try:
        exchange_class = getattr(ccxt_async, exchange_id)
        exchange = exchange_class({
            'enableRateLimit': True,
            'timeout': 15000,
        })
        tickers = await exchange.fetch_tickers()
        await exchange.close()
        return exchange_id, tickers
    except Exception as e:
        if exchange:
            try:
                await exchange.close()
            except:
                pass
        return exchange_id, None


async def scan_exchanges(exchange_ids, max_concurrent=20):
    results = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def limited_fetch(eid):
        async with semaphore:
            return await fetch_tickers_safe(eid)

    tasks = [limited_fetch(eid) for eid in exchange_ids]

    console.print(f"\n[bold cyan]Scanning {len(exchange_ids)} exchanges...[/bold cyan]\n")

    done_count = 0
    success_count = 0

    for coro in asyncio.as_completed(tasks):
        eid, tickers = await coro
        done_count += 1
        if tickers:
            results[eid] = tickers
            success_count += 1
            status = f"[green]✓ {eid}[/green]"
        else:
            status = f"[red]✗ {eid}[/red]"

        console.print(f"  [{done_count}/{len(exchange_ids)}] {status}", highlight=False)

    console.print(f"\n[bold green]Successfully fetched from {success_count}/{len(exchange_ids)} exchanges[/bold green]\n")
    return results


def is_leveraged_token(symbol):
    base = symbol.split('/')[0]
    return any(base.endswith(s) for s in LEVERAGED_SUFFIXES)


def normalize_symbol(symbol):
    return symbol.split(':')[0]


def find_arbitrage(all_tickers, min_profit_pct=MIN_PROFIT_PCT, min_volume=MIN_VOLUME_USD):
    coin_prices = {}

    for exchange_id, tickers in all_tickers.items():
        for symbol, ticker in tickers.items():
            if not ticker or not isinstance(ticker, dict):
                continue

            if '/USDT' not in symbol:
                continue

            norm = normalize_symbol(symbol)
            base = norm.split('/')[0]

            if base in STABLECOINS:
                continue
            if is_leveraged_token(norm):
                continue

            bid = ticker.get('bid')
            ask = ticker.get('ask')
            volume = ticker.get('quoteVolume') or 0

            if not bid or not ask or bid <= 0 or ask <= 0:
                continue
            if ask < MIN_PRICE or bid < MIN_PRICE:
                continue
            if volume < min_volume:
                continue
            if bid > ask * 1.5:
                continue

            if norm not in coin_prices:
                coin_prices[norm] = []

            coin_prices[norm].append({
                'exchange': exchange_id,
                'symbol': symbol,
                'bid': bid,
                'ask': ask,
                'volume': volume,
            })

    opportunities = []

    for pair, prices in coin_prices.items():
        if len(prices) < 2:
            continue

        median_price = sorted(p['ask'] for p in prices)[len(prices) // 2]

        filtered = [p for p in prices if 0.1 * median_price < p['ask'] < 10 * median_price]

        if len(filtered) < 2:
            continue

        for buy_entry in filtered:
            for sell_entry in filtered:
                if buy_entry['exchange'] == sell_entry['exchange']:
                    continue

                buy_price = buy_entry['ask']
                sell_price = sell_entry['bid']

                profit_pct = ((sell_price - buy_price) / buy_price) * 100

                if min_profit_pct <= profit_pct <= MAX_PROFIT_PCT:
                    coin = pair.split('/')[0]
                    opportunities.append({
                        'coin': coin,
                        'pair': pair,
                        'buy_exchange': buy_entry['exchange'],
                        'buy_symbol': buy_entry['symbol'],
                        'buy_price': buy_price,
                        'buy_volume': buy_entry['volume'],
                        'sell_exchange': sell_entry['exchange'],
                        'sell_symbol': sell_entry['symbol'],
                        'sell_price': sell_price,
                        'sell_volume': sell_entry['volume'],
                        'profit_pct': profit_pct,
                        'spread': sell_price - buy_price,
                    })

    opportunities.sort(key=lambda x: x['profit_pct'], reverse=True)
    return opportunities


def display_opportunities(opportunities, top_n=30):
    if not opportunities:
        console.print("[bold red]No arbitrage opportunities found above threshold.[/bold red]")
        return

    table = Table(
        title=f"🔥 Top {min(top_n, len(opportunities))} Arbitrage Opportunities",
        show_lines=True,
    )

    table.add_column("#", style="dim", width=4)
    table.add_column("Coin", style="bold cyan", width=10)
    table.add_column("Buy On", style="green", width=15)
    table.add_column("Buy Price", style="green", justify="right", width=14)
    table.add_column("Sell On", style="red", width=15)
    table.add_column("Sell Price", style="red", justify="right", width=14)
    table.add_column("Profit %", style="bold yellow", justify="right", width=10)
    table.add_column("Spread", justify="right", width=14)

    for i, opp in enumerate(opportunities[:top_n], 1):
        profit_style = "bold green" if opp['profit_pct'] >= 2 else "yellow"

        table.add_row(
            str(i),
            opp['coin'],
            opp['buy_exchange'],
            f"${opp['buy_price']:.6f}",
            opp['sell_exchange'],
            f"${opp['sell_price']:.6f}",
            f"[{profit_style}]{opp['profit_pct']:.2f}%[/{profit_style}]",
            f"${opp['spread']:.6f}",
        )

    console.print(table)
    console.print(f"\n[bold]Total opportunities found: {len(opportunities)}[/bold]")

    if opportunities:
        best = opportunities[0]
        console.print(Panel(
            f"[bold green]Best: {best['coin']}[/bold green]\n"
            f"Buy on [cyan]{best['buy_exchange']}[/cyan] at ${best['buy_price']:.6f}\n"
            f"Sell on [cyan]{best['sell_exchange']}[/cyan] at ${best['sell_price']:.6f}\n"
            f"Profit: [bold yellow]{best['profit_pct']:.2f}%[/bold yellow]",
            title="💰 Top Pick",
        ))


def save_results(opportunities, filename="results.json"):
    with open(f"/Users/udhaybhaskar/crypto-arb-scanner/{filename}", 'w') as f:
        json.dump(opportunities[:100], f, indent=2)
    console.print(f"[dim]Results saved to {filename}[/dim]")


async def main():
    console.print(Panel(
        "[bold cyan]Crypto Arbitrage Scanner[/bold cyan]\n"
        "Scanning 100+ exchanges for price differences",
        title="🔍 Scanner",
    ))

    exchange_ids = get_all_exchanges()
    console.print(f"[bold]Found {len(exchange_ids)} exchanges to scan[/bold]")

    start = time.time()
    all_tickers = await scan_exchanges(exchange_ids)
    scan_time = time.time() - start

    console.print(f"[dim]Scan completed in {scan_time:.1f}s[/dim]\n")

    console.print("[bold cyan]Analyzing price differences...[/bold cyan]")
    opportunities = find_arbitrage(all_tickers)

    display_opportunities(opportunities)
    save_results(opportunities)

    console.print(f"\n[dim]Run again: python3 scanner.py[/dim]")


if __name__ == '__main__':
    asyncio.run(main())
