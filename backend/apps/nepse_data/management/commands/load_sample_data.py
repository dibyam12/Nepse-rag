"""
Management command: python manage.py load_sample_data

Creates:
- Sectors: Commercial Banks, Hydropower, Insurance (Life),
           Insurance (Non-Life), Development Banks, Finance Companies,
           Microfinance, Manufacturing & Processing, Hotels & Tourism
- NepseIndex: NEPSE Index, Banking Sub-Index,
              Hydropower Sub-Index, Insurance Sub-Index
- Stocks: 60+ major NEPSE stocks with correct sector assignments

Sector assignments match real NEPSE classifications.
Uses get_or_create — safe to run multiple times.

Usage:
    python manage.py load_sample_data
"""
import logging
from django.core.management.base import BaseCommand
from apps.nepse_data.models import Sector, NepseIndex, Stock

logger = logging.getLogger('nepse_rag')


class Command(BaseCommand):
    help = 'Load NEPSE sectors, indexes, and 60+ stocks for development'

    def handle(self, *args, **options):
        self.stdout.write('Loading NEPSE sample data...\n')

        # ── Sectors ──────────────────────────────────────────────
        sectors_data = [
            {
                'name': 'Commercial Banks',
                'description': "Class 'A' banks licensed by Nepal Rastra Bank (NRB). "
                               "Largest and most systemically important financial "
                               "institutions in Nepal.",
            },
            {
                'name': 'Development Banks',
                'description': "Class 'B' financial institutions focusing on "
                               "development-oriented banking, project financing, "
                               "and regional banking services.",
            },
            {
                'name': 'Finance Companies',
                'description': "Class 'C' financial institutions offering hire "
                               "purchase, term loans, consumer finance, and "
                               "various credit facilities.",
            },
            {
                'name': 'Microfinance',
                'description': "Microfinance institutions providing small loans, "
                               "savings products, and financial services to "
                               "low-income and rural clients.",
            },
            {
                'name': 'Hydropower',
                'description': "Companies involved in hydroelectric power "
                               "generation, transmission, or related infrastructure "
                               "in Nepal.",
            },
            {
                'name': 'Insurance (Life)',
                'description': "Life insurance companies regulated by Beema Samiti. "
                               "Provide life insurance, endowment policies, and "
                               "long-term protection products.",
            },
            {
                'name': 'Insurance (Non-Life)',
                'description': "Non-life (general) insurance companies providing "
                               "motor, fire, marine, health, and property insurance.",
            },
            {
                'name': 'Manufacturing & Processing',
                'description': "Companies engaged in industrial production such as "
                               "cement, steel, food and beverages, pharmaceuticals, "
                               "and other processed goods.",
            },
            {
                'name': 'Hotels & Tourism',
                'description': "Listed hotels, resorts, and tourism-related "
                               "companies serving domestic and international travelers.",
            },
        ]

        created_sectors = 0
        existing_sectors = 0
        sectors = {}
        for s in sectors_data:
            obj, created = Sector.objects.get_or_create(
                name=s['name'],
                defaults={'description': s['description']}
            )
            sectors[s['name']] = obj
            if created:
                created_sectors += 1
                self.stdout.write(f'  Sector: {obj.name} [CREATED]')
            else:
                existing_sectors += 1
                self.stdout.write(f'  Sector: {obj.name} [EXISTS]')

        # ── Indexes ──────────────────────────────────────────────
        indexes_data = [
            {
                'name': 'NEPSE Index',
                'description': 'Primary index of Nepal Stock Exchange, '
                               'tracking all listed companies.',
            },
            {
                'name': 'Banking Sub-Index',
                'description': 'Sub-index tracking commercial and development '
                               'bank stocks on NEPSE.',
            },
            {
                'name': 'Hydropower Sub-Index',
                'description': 'Sub-index tracking hydropower sector stocks.',
            },
            {
                'name': 'Insurance Sub-Index',
                'description': 'Sub-index tracking life and non-life insurance '
                               'sector stocks.',
            },
        ]

        created_indexes = 0
        indexes = {}
        for idx in indexes_data:
            obj, created = NepseIndex.objects.get_or_create(
                name=idx['name'],
                defaults={'description': idx['description']}
            )
            indexes[idx['name']] = obj
            status = 'CREATED' if created else 'EXISTS'
            if created:
                created_indexes += 1
            self.stdout.write(f'  Index:  {obj.name} [{status}]')

        nepse_index = indexes['NEPSE Index']

        # ── Stocks ───────────────────────────────────────────────
        stocks_data = [
            # Commercial Banks (20)
            ('NABIL', 'Nabil Bank Limited', 'Commercial Banks'),
            ('EBL', 'Everest Bank Limited', 'Commercial Banks'),
            ('SANIMA', 'Sanima Bank Limited', 'Commercial Banks'),
            ('HBL', 'Himalayan Bank Limited', 'Commercial Banks'),
            ('NICA', 'NIC Asia Bank Limited', 'Commercial Banks'),
            ('KBL', 'Kumari Bank Limited', 'Commercial Banks'),
            ('CZBIL', 'Citizens Bank International Limited', 'Commercial Banks'),
            ('SBI', 'Nepal SBI Bank Limited', 'Commercial Banks'),
            ('MBL', 'Machhapuchchhre Bank Limited', 'Commercial Banks'),
            ('SBL', 'Siddhartha Bank Limited', 'Commercial Banks'),
            ('LBL', 'Laxmi Sunrise Bank Limited', 'Commercial Banks'),
            ('SCB', 'Standard Chartered Bank Nepal Limited', 'Commercial Banks'),
            ('SRBL', 'Sunrise Bank Limited', 'Commercial Banks'),
            ('PCBL', 'Prime Commercial Bank Limited', 'Commercial Banks'),
            ('GBIME', 'Global IME Bank Limited', 'Commercial Banks'),
            ('NBB', 'Nepal Bangladesh Bank Limited', 'Commercial Banks'),
            ('ADBL', 'Agriculture Development Bank Limited', 'Commercial Banks'),
            ('BOKL', 'Bank of Kathmandu Limited', 'Commercial Banks'),
            ('PRVU', 'Prabhu Bank Limited', 'Commercial Banks'),
            ('NMB', 'NMB Bank Limited', 'Commercial Banks'),

            # Hydropower (20)
            ('NHPC', 'Nepal Hydro Power Company Limited', 'Hydropower'),
            ('AHPC', 'Arun Hydropower Company Limited', 'Hydropower'),
            ('CHCL', 'Chilime Hydropower Company Limited', 'Hydropower'),
            ('AKPL', 'Arun Kabeli Power Limited', 'Hydropower'),
            ('RURU', 'Ruru Jalbidhyut Pariyojana Limited', 'Hydropower'),
            ('UMHL', 'United Modi Hydropower Limited', 'Hydropower'),
            ('SHPC', 'Sanjen Hydropower Company Limited', 'Hydropower'),
            ('HPPL', 'Himalayan Power Partner Limited', 'Hydropower'),
            ('GHL', 'Gurans Hydropower Limited', 'Hydropower'),
            ('NHDL', 'Nepal Hydro Developers Limited', 'Hydropower'),
            ('RADHI', 'Radhi Bidyut Company Limited', 'Hydropower'),
            ('RHPC', 'Rairang Hydropower Development Company Limited', 'Hydropower'),
            ('API', 'Api Power Company Limited', 'Hydropower'),
            ('UPPER', 'Upper Tamakoshi Hydropower Limited', 'Hydropower'),
            ('NGPL', 'National Generation Power Limited', 'Hydropower'),
            ('PMHPL', 'Peoples Hydropower Company Limited', 'Hydropower'),
            ('SSHL', 'Solu Hydropower Limited', 'Hydropower'),
            ('BHL', 'Barun Hydropower Limited', 'Hydropower'),
            ('MHNL', 'Molung Hydropower Limited', 'Hydropower'),
            ('GLH', 'Galchi Hydropower Limited', 'Hydropower'),

            # Insurance (Life + Non-Life) (17)
            ('NLIC', 'Nepal Life Insurance Company Limited', 'Insurance (Life)'),
            ('NLG', 'NLG Insurance Company Limited', 'Insurance (Non-Life)'),
            ('PRIN', 'Prime Life Insurance Company Limited', 'Insurance (Life)'),
            ('SICL', 'Shikhar Insurance Company Limited', 'Insurance (Non-Life)'),
            ('UICL', 'United Insurance Company Limited', 'Insurance (Non-Life)'),
            ('HGI', 'Himalayan General Insurance Company Limited', 'Insurance (Non-Life)'),
            ('IGIL', 'IME General Insurance Limited', 'Insurance (Non-Life)'),
            ('AIL', 'Asian Life Insurance Company Limited', 'Insurance (Life)'),
            ('SIC', 'Sagarmatha Insurance Company Limited', 'Insurance (Non-Life)'),
            ('PICL', 'Pioneer Insurance Company Limited', 'Insurance (Non-Life)'),
            ('SGIC', 'Siddhartha Insurance Company Limited', 'Insurance (Non-Life)'),
            ('LICN', 'Life Insurance Corporation Nepal', 'Insurance (Life)'),
            ('RBCL', 'Reliable Insurance Company Limited', 'Insurance (Non-Life)'),
            ('PLIC', 'Prabhu Insurance Limited', 'Insurance (Non-Life)'),
            ('SLICL', 'Surya Life Insurance Company Limited', 'Insurance (Life)'),
            ('ALICL', 'Asian Life Insurance Company Limited', 'Insurance (Life)'),
            ('CLI', 'Citizens Life Insurance Company Limited', 'Insurance (Life)'),

            # Development Banks (5)
            ('GBBL', 'Garima Bikas Bank Limited', 'Development Banks'),
            ('MLBL', 'Mahalaxmi Bikas Bank Limited', 'Development Banks'),
            ('MNBBL', 'Muktinath Bikas Bank Limited', 'Development Banks'),
            ('SADBL', 'Shangrila Development Bank Limited', 'Development Banks'),
            ('KSBBL', 'Kamana Sewa Bikas Bank Limited', 'Development Banks'),

            # Microfinance (5)
            ('CBBL', 'Chhimek Bikas Bank Limited', 'Microfinance'),
            ('SMFDB', 'Swabalamban Laghubitta Bittiya Sanstha Limited', 'Microfinance'),
            ('SWBBL', 'Swarojgar Laghubitta Bittiya Sanstha Limited', 'Microfinance'),
            ('RMDC', 'RMDC Laghubitta Bittiya Sanstha Limited', 'Microfinance'),
            ('CFCL', 'Central Finance Limited', 'Finance Companies'),

            # Manufacturing & Processing (3)
            ('UNL', 'Unilever Nepal Limited', 'Manufacturing & Processing'),
            ('BNT', 'Bottlers Nepal Terai Limited', 'Manufacturing & Processing'),
            ('HDL', 'Himalayan Distillery Limited', 'Manufacturing & Processing'),

            # Hotels & Tourism (3)
            ('TRH', 'Taragaon Regency Hotel Limited', 'Hotels & Tourism'),
            ('SHL', 'Soaltee Hotel Limited', 'Hotels & Tourism'),
            ('OHL', 'Oriental Hotels Limited', 'Hotels & Tourism'),
        ]

        created_stocks = 0
        existing_stocks = 0
        updated_stocks = 0
        for sym, name, sector_name in stocks_data:
            obj, created = Stock.objects.get_or_create(
                symbol=sym,
                defaults={
                    'name': name,
                    'sector': sectors.get(sector_name),
                    'index': nepse_index,
                    'is_active': True,
                }
            )
            if created:
                created_stocks += 1
            else:
                existing_stocks += 1
                # Update sector/index if missing (e.g., auto-created from Neon)
                changed = False
                if obj.sector is None and sector_name in sectors:
                    obj.sector = sectors[sector_name]
                    changed = True
                if obj.index is None:
                    obj.index = nepse_index
                    changed = True
                if changed:
                    obj.save()
                    updated_stocks += 1

        self.stdout.write(f'\n  Stocks created: {created_stocks}')
        self.stdout.write(f'  Stocks updated (sector/index): {updated_stocks}')
        self.stdout.write(f'  Stocks already existed: {existing_stocks}')

        self.stdout.write(self.style.SUCCESS(
            f'\nSample data loaded successfully!\n'
            f'  {created_sectors} sectors created '
            f'({existing_sectors} already existed)\n'
            f'  {created_indexes} indexes created\n'
            f'  {created_stocks} stocks created '
            f'({existing_stocks} already existed)\n'
            f'  Total stocks in DB: {Stock.objects.count()}'
        ))
        logger.info('Sample data loaded', extra={
            'event': 'load_sample_data',
            'sectors': len(sectors_data),
            'indexes': len(indexes_data),
            'stocks_created': created_stocks,
            'stocks_existed': existing_stocks,
        })
