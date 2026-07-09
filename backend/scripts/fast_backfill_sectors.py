import os
import sys
import re
from pathlib import Path

# Setup Django environment
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'nepse_project.settings')
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

import django
django.setup()

from apps.nepse_data.models import Stock, Sector

# Valid canonical sectors
SECTOR_NAMES = [
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

# Base symbols mapping to sector
BASE_MAPPINGS = {
    # Commercial Banks
    'Commercial Banks': [
        'ADBL', 'BOKL', 'CZBIL', 'EBL', 'GBIME', 'HBL', 'KBL', 'LBL', 'MBL', 'NABIL', 
        'NBB', 'NICA', 'NMB', 'PCBL', 'PRVU', 'SANIMA', 'SBI', 'SBL', 'SCB', 'SRBL', 
        'NIB', 'NIBL', 'CBL', 'CCBL', 'MEGA', 'LSL', 'BOK', 'NIMB'
    ],
    # Development Banks
    'Development Banks': [
        'CORBL', 'EDBL', 'GBBL', 'GRDBL', 'JBBL', 'JSBB', 'KRBL', 'LBBL', 'MDB', 'MLBL', 
        'MNBBL', 'SADBL', 'SAPDBL', 'SHINE', 'SINHE', 'DBBL', 'KSBBL', 'EDBL'
    ],
    # Finance Companies
    'Finance Companies': [
        'BFC', 'CFCL', 'GFCL', 'GMFIL', 'GUFL', 'ICFC', 'JFL', 'MFIL', 'MPFL', 'NFS', 
        'PFL', 'RLFL', 'SFCL', 'SIFC', 'JEFL', 'PROFL', 'UFL'
    ],
    # Hotels & Tourism
    'Hotels & Tourism': [
        'OHL', 'SHL', 'TRH', 'CGH', 'KDL', 'KHL', 'LTC'
    ],
    # Hydropower
    'Hydropower': [
        'AHL', 'AHPC', 'AKJCL', 'AKPL', 'API', 'BARUN', 'BGWT', 'BHCL', 'BHDC', 'BHL', 
        'BHPL', 'BJHL', 'BNHC', 'BPCL', 'BUNGAL', 'CHCL', 'CHDC', 'CHL', 'CKHL', 'DHEL', 
        'DHPL', 'DOLTI', 'DORDI', 'EHPL', 'GHL', 'GLH', 'GVL', 'HHL', 'HPPL', 'HURJA', 
        'IHL', 'JOSHI', 'KKHC', 'LEC', 'MABEL', 'MANDU', 'MBJC', 'MHCL', 'MHL', 'MHNL', 
        'MKCL', 'MKHC', 'MKHL', 'MKJC', 'MMKJL', 'NGPL', 'NHDL', 'NHPC', 'PMHPL', 
        'RADHI', 'RHPC', 'RURU', 'SHPC', 'SSHL', 'UMHL', 'UPPER', 'USHEC', 'KPCL', 
        'HDHPC', 'SPDL', 'SJCL', 'SPHL', 'TSHL', 'PHCL', 'MEN', 'MEHL', 'MEL', 'MAKAR', 
        'SGHC', 'SHEL', 'SMHL', 'SPL', 'SPC', 'SVAL', 'TACL', 'TPCL', 'TVCL', 'UUHP', 
        'SMJC', 'NYADI', 'NGM', 'MDHC', 'MCHL', 'KPL', 'KHDGB', 'KHE', 'KKJCL', 'SHEAL', 
        'SGWJ', 'TJHCL', 'MHGP', 'SGHL', 'CIC', 'EHP', 'HEI', 'HPG', 'JALPA' # wait, JALPA is microfinance!
    ],
    # Insurance (Life)
    'Insurance (Life)': [
        'ALICL', 'CLICL', 'LICN', 'NLIC', 'NLICL', 'PLI', 'RLI', 'SJLIC', 'SLI', 'SLICL', 
        'ELIC', 'ILI', 'IMEL', 'MEELI', 'SURYAL', 'ALIC', 'CLI', 'NLIC'
    ],
    # Insurance (Non-Life)
    'Insurance (Non-Life)': [
        'GICL', 'HGI', 'IGI', 'LGIL', 'NGI', 'NICL', 'NLG', 'PRIN', 'SICL', 'SIL', 
        'UAIL', 'NLG', 'EIC', 'NIL', 'SIC', 'UIC', 'NIC'
    ],
    # Manufacturing & Processing
    'Manufacturing & Processing': [
        'BNT', 'UNL', 'SHIVM', 'HDL', 'GCIL', 'SONA', 'SAR', 'GCIL'
    ],
    # Microfinance
    'Microfinance': [
        'ACLBSL', 'ALBSL', 'ANLB', 'AVYAN', 'DDBL', 'DLBS', 'FMDBL', 'FOWAD', 'GBLBS', 
        'GILB', 'GLBSL', 'GMFBS', 'JALPA', 'KMCDB', 'LLBS', 'MERO', 'MLBBL', 'MSLB', 
        'NESDO', 'NIBTL', 'NMBMF', 'RSDC', 'SADLH', 'SALBSL', 'SDFS', 'SKBBL', 'SMB', 
        'SMFDB', 'SNLB', 'SPBS', 'SWBHC', 'USLB', 'VLBS', 'WNLB', 'CYCL', 'MATRI', 
        'MMDB', 'ILBS', 'HLBS', 'MSLBS', 'NLBSL', 'SMABS', 'MLBSL', 'NICLBSL', 'CLBSL', 
        'JSLBB', 'KMFL', 'SMATA', 'SDLBSL', 'BPW', 'MSLB', 'NESDO', 'SMFDB'
    ]
}

# Reverse mapping for base symbol lookup
SYMBOL_TO_SECTOR = {}
for sector, symbols in BASE_MAPPINGS.items():
    for sym in symbols:
        SYMBOL_TO_SECTOR[sym.upper()] = sector

def get_base_symbol(symbol: str) -> str:
    """Strips debenture, bond, promoter and mutual fund suffixes from symbol to find base."""
    sym = symbol.upper()
    
    # 1. Check if direct match first
    if sym in SYMBOL_TO_SECTOR:
        return sym
        
    # 2. Try removing common suffixes:
    # - Debenture endings like D83, D84, D85, D86, D87, D88, D91, D2082, D80/81, D84/85, D86/87, etc.
    # - Bond endings like B86, B87, etc.
    # - Promoter/Preference shares like PO, P, PP, PPO
    # - Star / Equity / Bluechip / Mutual Fund endings like S1, F1, F2, BS, EF, GF, LGF, LPF, PF
    # Match symbol prefixes of length 3 to 6
    m = re.match(r'^([A-Z]{3,6})(?:D\d+|B\d+|\d+/\d+|PO|P|PP|PPO|S1|F1|F2|BS|EF|GF|LGF|LPF|PF)$', sym)
    if m:
        prefix = m.group(1)
        if prefix in SYMBOL_TO_SECTOR:
            return prefix
            
    # Try generic prefix search: find if the symbol starts with any known base symbol
    for base in sorted(SYMBOL_TO_SECTOR.keys(), key=len, reverse=True):
        if sym.startswith(base) and len(sym) > len(base):
            # Check if remainder is numeric or typical suffix
            rem = sym[len(base):]
            if re.match(r'^(?:D?\d+|B?\d+|\d+/\d+|PO|P|PP|PPO|S1|F1|F2|BS|EF|GF|LGF|LPF|PF)?$', rem):
                return base
                
    return sym

def classify_stock(stock) -> str | None:
    symbol = stock.symbol.upper()
    name = stock.name.lower()
    
    # Check base symbol match
    base_sym = get_base_symbol(symbol)
    if base_sym in SYMBOL_TO_SECTOR:
        return SYMBOL_TO_SECTOR[base_sym]
        
    # Check general microfinance ending rules
    if any(symbol.endswith(k) for k in ['LBS', 'LBSL', 'LB']):
        return 'Microfinance'
        
    # Check general hydropower ending rules
    if any(symbol.endswith(k) for k in ['HP', 'HPL', 'JCL']):
        return 'Hydropower'
        
    # Check name heuristics if not auto-created
    if 'auto-created' not in name and name.strip() != '':
        if any(k in name for k in ['laghubitta', 'microfinance', 'micro-finance', 'bittiya sanstha']):
            return 'Microfinance'
        if any(k in name for k in ['hydropower', 'hydro power', 'jalbidhyut', 'jalvidhyut', 'power company', 'power developer']):
            return 'Hydropower'
        if 'life insurance' in name or 'life beema' in name:
            return 'Insurance (Life)'
        if 'insurance' in name or 'beema' in name or 'bima' in name:
            if any(k in name for k in ['non-life', 'non life', 'general']):
                return 'Insurance (Non-Life)'
            return 'Insurance (Life)'
        if any(k in name for k in ['development bank', 'bikash bank', 'bikas bank']):
            return 'Development Banks'
        if 'finance' in name:
            return 'Finance Companies'
        if 'bank' in name:
            return 'Commercial Banks'
            
    return None

def main():
    print("Initializing fast local backfill...")
    sector_map = {s.name: s for s in Sector.objects.all()}
    
    # 1. Reset all stocks that might be misclassified
    mismatched_symbols = [
        'ACLBSLP', 'ADBLB86', 'ADBLD83', 'ALICLP', 'AVYAN', 'BFC', 'BOKD86', 'C30MF', 
        'CBLD88', 'CCBD88', 'CIZBD86', 'CMF2', 'FOWAD', 'FOWADP', 'GBBD85', 'GIBF1', 
        'HIMSTAR', 'MEROPO', 'NBF2', 'NBLD85', 'NIBD2082', 'BBC', 'CIT', 'CMF1', 
        'LVF1', 'LVF2', 'MBLEF', 'MDB', 'MDBPO', 'MERO', 'NIBLGF', 'NIBLPF'
    ]
    Stock.objects.filter(symbol__in=mismatched_symbols).update(sector=None)
    print(f"Reset {len(mismatched_symbols)} potentially mismatched symbols to sector=None.")
    
    # 2. Iterate through all stocks and classify
    stocks = Stock.objects.all()
    updated_count = 0
    skipped_count = 0
    unmatched_list = []
    
    for s in stocks:
        current_sector = s.sector.name if s.sector else None
        target_sector_name = classify_stock(s)
        
        if target_sector_name:
            if current_sector != target_sector_name:
                s.sector = sector_map[target_sector_name]
                s.save()
                updated_count += 1
                # print(f"Updated {s.symbol} -> {target_sector_name}")
            else:
                skipped_count += 1
        else:
            # Leave sector as None for mutual funds, index, bonds of unmapped companies, etc.
            if s.sector is not None:
                s.sector = None
                s.save()
                updated_count += 1
            unmatched_list.append(s.symbol)
            skipped_count += 1
            
    print("\n==================================================")
    print("FAST BACKFILL COMPLETE SUMMARY:")
    print(f"  Total stocks in DB: {stocks.count()}")
    print(f"  Total mapped and updated: {updated_count}")
    print(f"  Total skipped/unchanged: {skipped_count}")
    print(f"  Total unmatched/None (logged to unmatched_sectors.txt): {len(unmatched_list)}")
    print("==================================================")
    
    # Log unmatched
    script_dir = Path(__file__).resolve().parent
    with open(script_dir / "unmatched_sectors.txt", "w") as f:
        f.write("\n".join(unmatched_list))
        
    # Get active counts
    active_counts = list(Stock.objects.values('sector__name').annotate(count=django.db.models.Count('id')))
    print("\nCURRENT SECTOR COUNTS IN DB:")
    for item in active_counts:
        print(f"  {item['sector__name'] or 'None (Mutual Funds/Unmapped)'}: {item['count']}")

if __name__ == '__main__':
    main()
