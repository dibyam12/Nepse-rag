import os
import sys
import asyncio
import logging
import re
from pathlib import Path

# Setup Django environment
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import django
django.setup()

from apps.nepse_data.models import Stock, Sector
from services.web_search import _run_ddg_query

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger('backfill_sectors')

# Valid canonical sector names
CANONICAL_SECTORS = [
    'Commercial Banks',
    'Development Banks',
    'Finance Companies',
    'Hotels & Tourism',
    'Hydropower',
    'Insurance (Life)',
    'Insurance (Non-Life)',
    'Manufacturing & Processing',
    'Microfinance'
]

# Detailed keyword patterns to match search snippets to sectors (case-insensitive)
SECTOR_KEYWORDS = {
    'Commercial Banks': [
        'commercial bank', 'commercial banks', 'nabil bank', 'everest bank',
        'nic asia', 'standard chartered bank', 'nepal bank', 'global ime bank',
        'agriculture development bank', 'laxmi sunrise', 'prime bank', 'kumari bank',
        'siddharth bank', 'sanima bank', 'machhapuchchhre bank', 'prabhu bank',
        'himalayan bank', 'citizen bank', 'nepal sbi bank', 'banking sector'
    ],
    'Development Banks': [
        'development bank', 'development banks', 'bikash bank', 'bikas bank',
        'garima bikash', 'muktinath bikash', 'jyoti bikash', 'lumbini bikash',
        'kamana sewa', 'shangri-la', 'shangrila development', 'corporate development',
        'green development', 'mahalaxmi development', 'shine resunga', 'karnali development'
    ],
    'Finance Companies': [
        'finance company', 'finance companies', 'finance co', 'central finance',
        'manjushree finance', 'pokhara finance', 'gurkhas finance', 'reliance finance',
        'shree investment', 'icfc finance', 'samriddhi finance', 'lumbini finance',
        'progressive finance', 'guheswori'
    ],
    'Hotels & Tourism': [
        'hotel', 'hotels', 'tourism', 'resort', 'soaltee', 'taragaon', 'chandragiri',
        'yak and yeti', 'oriental hotels', 'kalinchowk'
    ],
    'Hydropower': [
        'hydropower', 'hydro power', 'hydroelectric', 'hydro electricity', 'power developer',
        'power company', 'giri khola', 'madi power', 'super mai', 'khani khola',
        'rasuwagadhi', 'chilime', 'sanjyen', 'upper tamakoshi', 'butwal power',
        'arun valley', 'barun hydropower', 'api power', 'riri hydropower', 'nhpc'
    ],
    'Insurance (Life)': [
        'life insurance', 'life co', 'lic nepal', 'national life insurance',
        'nepal life', 'citizen life', 'reliable nepal life', 'suryajyoti life',
        'sun nepal life', 'i.m.e. life', 'asian life insurance', 'prabhu life'
    ],
    'Insurance (Non-Life)': [
        'non-life insurance', 'non life insurance', 'general insurance',
        'sagarmatha lumbini', 'himalayan general', 'shikhar insurance', 'nlg insurance',
        'sidhartha insurance', 'nepal insurance', 'united ajod', 'prabhu insurance'
    ],
    'Manufacturing & Processing': [
        'manufacturing', 'processing', 'distillery', 'cement', 'himalayan distillery',
        'shivam cement', 'ghorahi cement', 'sonapur cement', 'bottlers nepal',
        'unilever nepal'
    ],
    'Microfinance': [
        'microfinance', 'micro-finance', 'laghubitta', 'laghubit', 'micro finance',
        'sana kisan', 'chayanout', 'deprosc', 'swabalamban', 'nirdhan', 'forward microfinance',
        'nerude', 'mithila', 'jeevan bikas', 'nesdo'
    ]
}

def clean_company_name(name: str) -> str:
    """Removes (auto-created...) and other noise from company name."""
    name = re.sub(r'\(auto-created.*?\)', '', name)
    name = re.sub(r'\(.*?\)', '', name)
    return name.strip()

def match_sector_from_snippets(snippets: list[str]) -> str | None:
    """Matches text snippets against sector keyword lists and returns canonical name if confident."""
    sector_scores = {s: 0 for s in CANONICAL_SECTORS}
    combined_text = " | ".join(snippets).lower()
    
    for sector, keywords in SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in combined_text:
                sector_scores[sector] += 1
                
    best_sector = None
    best_score = 0
    for sector, score in sector_scores.items():
        if score > best_score:
            best_score = score
            best_sector = sector
            
    if best_score > 0:
        return best_sector
    return None

def map_symbol_to_sector_locally(symbol: str, company_name: str, sector_map: dict, existing_stocks: dict) -> Sector | None:
    """Uses pattern matching on symbol/name and existing base symbols to resolve sector offline."""
    name_lower = company_name.lower()
    sym_upper = symbol.upper()
    
    # 1. Local name checks (if the name is valid and not auto-created)
    if "auto-created" not in name_lower and name_lower.strip() != "":
        # Microfinance
        if any(k in name_lower for k in ['laghubitta', 'microfinance', 'micro-finance', 'micro finance', 'bittiya sanstha']):
            return sector_map.get('Microfinance')
            
        # Hydropower
        if any(k in name_lower for k in ['hydropower', 'hydro power', 'jalbidhyut', 'jalvidhyut', 'power company', 'power developer', 'geetanjali']):
            return sector_map.get('Hydropower')
            
        # Insurance (Life / Non-Life)
        if 'life insurance' in name_lower or 'life beema' in name_lower:
            return sector_map.get('Insurance (Life)')
        if 'insurance' in name_lower or 'beema' in name_lower or 'bima' in name_lower:
            if any(k in name_lower for k in ['non-life', 'non life', 'general', 'sagarmatha', 'himalayan', 'shikhar', 'nlg', 'united', 'prabhu']):
                return sector_map.get('Insurance (Non-Life)')
            return sector_map.get('Insurance (Life)')
            
        # Development Banks
        if any(k in name_lower for k in ['development bank', 'bikash bank', 'bikas bank']):
            return sector_map.get('Development Banks')
            
        # Finance Companies
        if 'finance' in name_lower:
            return sector_map.get('Finance Companies')
            
        # Commercial Banks
        if 'bank' in name_lower:
            return sector_map.get('Commercial Banks')

    # 2. Local symbol checks
    # Ends with laghubitta patterns
    if any(sym_upper.endswith(k) for k in ['LBS', 'LBSL', 'LB']):
        return sector_map.get('Microfinance')
        
    # Ends with hydropower patterns
    if any(sym_upper.endswith(k) for k in ['HP', 'HPL', 'JCL']):
        return sector_map.get('Hydropower')

    # 3. Base Symbol Suffix Inheritance
    # Suffix patterns:
    # - Debentures: ends with D + digits (e.g. D85, D91, D80/81)
    # - Bonds: ends with B + digits (e.g. B86)
    # - Promoter/Preference: ends with PO, P, PP (e.g. EBLPO, GBIMEP, ACLBSLP)
    m = re.match(r'^([A-Z]{2,6})(?:D\d+|B\d+|\d+/\d+|PO|P|PP)$', sym_upper)
    if m:
        base_sym = m.group(1)
        if base_sym in existing_stocks:
            base_sector = existing_stocks[base_sym]
            if base_sector:
                return base_sector
                
    # Direct prefix match: check if sym starts with a known stock symbol and is longer than it
    for known_sym, base_sector in existing_stocks.items():
        if len(known_sym) >= 3 and sym_upper.startswith(known_sym) and len(sym_upper) > len(known_sym):
            rem = sym_upper[len(known_sym):]
            # Verify remainder is just numbers, PO, P, etc.
            if re.match(r'^(?:D?\d+|B?\d+|\d+/\d+|PO|P|PP|LBS|LBSL)?$', rem):
                return base_sector
                
    return None

async def main():
    # Cache sectors
    sector_map = {s.name: s for s in Sector.objects.all()}
    
    # Cache existing stock symbol to sector mappings
    existing_stocks = {}
    for stock in Stock.objects.exclude(sector__isnull=True).exclude(sector__name='Unknown').exclude(sector__name='').select_related('sector'):
        existing_stocks[stock.symbol.upper()] = stock.sector
        
    # Get stocks without a valid sector
    unmatched_stocks = Stock.objects.filter(
        sector__isnull=True
    ) | Stock.objects.filter(
        sector__name='Unknown'
    ) | Stock.objects.filter(
        sector__name=''
    )
    
    unmatched_stocks = unmatched_stocks.distinct()
    
    total_already_had = len(existing_stocks)
    total_to_process = unmatched_stocks.count()
    
    print(f"DATABASE AUDIT:")
    print(f"  Stocks with valid sectors: {total_already_had}")
    print(f"  Stocks needing backfill: {total_to_process}")
    
    if total_to_process == 0:
        print("No stocks need backfill. Exiting.")
        return
        
    matched_count = 0
    local_match_count = 0
    search_match_count = 0
    skipped_count = 0
    processed_count = 0
    
    unmatched_list = []
    backfilled_mappings = []
    
    script_dir = Path(__file__).resolve().parent
    review_file_path = script_dir / "unmatched_sectors.txt"
    
    print("\nStarting search-based backfill with local rules + search fallbacks...")
    
    loop = asyncio.get_event_loop()
    
    for i, stock in enumerate(unmatched_stocks, start=1):
        symbol = stock.symbol
        company_name = clean_company_name(stock.name)
        
        # Double check if sector got updated in this run
        stock.refresh_from_db()
        if stock.sector and stock.sector.name in CANONICAL_SECTORS:
            skipped_count += 1
            processed_count += 1
            continue
            
        # Try local rules mapping first
        matched_sector = map_symbol_to_sector_locally(symbol, company_name, sector_map, existing_stocks)
        
        if matched_sector:
            # Local match
            stock.sector = matched_sector
            stock.save()
            local_match_count += 1
            matched_count += 1
            backfilled_mappings.append((symbol, matched_sector.name))
            logger.info("Local Match [%d/%d]: %s -> %s", i, total_to_process, symbol, matched_sector.name)
        else:
            # Fallback to DDG search
            query = f"{symbol} site:sharesansar.com"
            matched_sector_name = None
            
            try:
                results = await loop.run_in_executor(None, _run_ddg_query, query, 3, "y")
                snippets = [r.get('body') or r.get('description') or '' for r in results]
                snippets = [s for s in snippets if s]
                
                matched_sector_name = match_sector_from_snippets(snippets)
                
                # Fallback: Try general query
                if not matched_sector_name:
                    fallback_query = f"{symbol} {company_name} NEPSE sector"
                    fallback_results = await loop.run_in_executor(None, _run_ddg_query, fallback_query, 3, "y")
                    fallback_snippets = [r.get('body') or r.get('description') or '' for r in fallback_results]
                    fallback_snippets = [s for s in fallback_snippets if s]
                    matched_sector_name = match_sector_from_snippets(fallback_snippets)
                    
            except Exception as e:
                logger.error("DDG search failed for %s: %s", symbol, e)
                
            if matched_sector_name:
                sector_obj = sector_map[matched_sector_name]
                stock.sector = sector_obj
                stock.save()
                search_match_count += 1
                matched_count += 1
                backfilled_mappings.append((symbol, matched_sector_name))
                logger.info("Search Match [%d/%d]: %s -> %s", i, total_to_process, symbol, matched_sector_name)
                # Small polite delay only when we actually search
                await asyncio.sleep(1.0)
            else:
                unmatched_list.append(f"{symbol} | {company_name}")
                logger.warning("Unmatched [%d/%d]: %s (%s)", i, total_to_process, symbol, company_name)
                # Small polite delay only when we actually search
                await asyncio.sleep(1.0)
                
        processed_count += 1
        if processed_count % 10 == 0:
            print(f"Progress: processed {processed_count}/{total_to_process}...")
            
    # Write unmatched stocks to review file
    with open(review_file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(unmatched_list))
        
    print("\n==================================================")
    print("BACKFILL COMPLETE SUMMARY:")
    print(f"  Total already had a sector: {total_already_had}")
    print(f"  Total processed in this run: {processed_count}")
    print(f"  Total matched and backfilled: {matched_count}")
    print(f"    - Local rules matched: {local_match_count}")
    print(f"    - Search fallbacks matched: {search_match_count}")
    print(f"  Total unmatched (logged to backend/scripts/unmatched_sectors.txt): {len(unmatched_list)}")
    print("==================================================")
    
    # Print sample mapping for manual check
    sample_mappings = backfilled_mappings[:20]
    print(f"\nSAMPLE BACKFILLED MAPPINGS (Sample of {len(sample_mappings)}):")
    for sym, sec in sample_mappings:
        print(f"  {sym} -> {sec}")

if __name__ == '__main__':
    asyncio.run(main())
