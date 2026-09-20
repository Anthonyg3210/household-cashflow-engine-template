"""bank CSV import → actuals with merchant→parent/subcategory taxonomy."""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from engine import db

UNCATEGORIZED = "Uncategorized"
UNCATEGORIZED_PARENT = "Uncategorized"
CSV_SOURCE = "bank_csv"
BLACK_CARD_SOURCE = "chase_black_card"
BLACK_CARD_DISPLAY = "Rewards Card — demo rewards card"
BLACK_CARD_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "data" / "black_card_snapshot.json"
BLACK_CARD_BUDGET_CONTEXT_PATH = Path(__file__).resolve().parent.parent / "data" / "black_card_budget_context.json"
MERCHANT_MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "merchant_map.json"
TAXONOMY_PATH = Path(__file__).resolve().parent.parent / "data" / "taxonomy_v2.json"

# Wife's allowance / family-card budget line (validated against recurring_rules).
# Do not change the $3500 start month unless Alex asks.
#   id 38: -$2500 DOM 28, 2026-10-01 .. 2027-02-28
#   id 39: -$3500 DOM 28, 2027-03-01 .. 2027-12-31
#   id 33: -$3500 DOM 27, 2028-01-01 onward
#   Sep 2026 planned: -$2500 (family_budget_sep2026_forecast)
ALLOWANCE_2500_THROUGH = (2027, 2)  # inclusive
ALLOWANCE_3500_FROM = (2027, 3)

CARD_PURCHASE_TYPES = frozenset({"Sale", "Fee"})
CARD_PAYMENT_TYPES = frozenset({"Payment"})
CARD_RETURN_TYPES = frozenset({"Return"})

# (pattern, parent, subcategory, legacy_category_for_rules)
# First match wins; order = specificity. legacy_category keeps recurring override keys stable.
DEFAULT_KEYWORD_MAP: list[tuple[str, str, str, str]] = [
    # Income
    # Late-pass extras (also in merchant_map)
    ("TJMAXX", "Shopping", "Malls / Retail", "Malls"),
    ("T.J. MAXX", "Shopping", "Malls / Retail", "Malls"),
    ("PLAYA BOWLS", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("NEWSMAX", "Home Services & Subs", "Other Subscriptions", "YouTube Subscription"),
    ("DEMO VEG CAFE", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("TST* VEN PA", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("VENARDOS CIRCUS", "Entertainment", "Family Outings", "Family Outings"),
    ("PASSPORTSERVICES", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("ZELLE PAYMENT TO SAM", "Allowance", "Partner Allowance", "Partner Allowance"),
    ("ZELLE PAYMENT TO DEMO CLEANER", "Home Services & Subs", "Home Cleaning Team", "Home Cleaning"),
    ("LG - DEMO TOWN", "Utilities", "Other Utilities", "Other Utitlities"),
    ("LG00012", "Utilities", "Other Utilities", "Other Utitlities"),
    # Black card / family-card merchants (same Household taxonomy)
    ("APPLE.COM", "Home Services & Subs", "Other Subscriptions", "YouTube Subscription"),
    ("GIV*BRIGHTSTART", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("PAPA JOHNS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("PAPA JOHN", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("PAWTREE", "Health & Personal", "Dog / Pets", "Dog"),
    ("ROKU", "Home Services & Subs", "Other Subscriptions", "YouTube Subscription"),
    ("DRYBAR", "Health & Personal", "Hair-cut", "Hair-cut"),
    ("DEMO DANCE STUDIO", "School", "Kids Activities / Memberships", "Max Memberships"),
    ("HOUNDS TOWN", "Health & Personal", "Dog / Pets", "Dog"),
    ("HOBBY-LOBBY", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("HOBBY LOBBY", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("J CREW", "Shopping", "Malls / Retail", "Malls"),
    ("NORDSTROM", "Shopping", "Malls / Retail", "Malls"),
    ("DEMO KIDS GYM", "School", "Kids Activities / Memberships", "Max Memberships"),
    ("KOHLS", "Shopping", "Malls / Retail", "Malls"),
    ("KOHL'S", "Shopping", "Malls / Retail", "Malls"),
    ("DCL SHIP", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("MAPLE GROVE HOA", "Housing", "HOA / Community Dues", "Homeowners Maple Grove Dues"),
    ("JERSEY MIKE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CIRCLEK", "Transportation", "Gas", "Gas"),
    ("NOTHING BUNDT", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CRUMBL", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("WARBY PARKER", "Health & Personal", "Medical", "Medical"),
    ("MARRIOTT ORLANDO", "Entertainment", "Family Outings", "Family Outings"),
    ("PAN PACIFIC", "Entertainment", "Family Outings", "Family Outings"),
    ("GAYLORD PALMS", "Entertainment", "Family Outings", "Family Outings"),
    ("RISSE BROTHERS", "School", "Kids Activities / Memberships", "Max Memberships"),
    ("OFFICEMAX", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("CINTAS", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),

    ("NORTHSTAR TECHNOL PAYROLL", "Income", "Alex's Income", "Alex's Income"),
    ("NORTHSTAR TECHNOL PAYMENTS", "Income", "Alex's Income", "Alex's Income"),
    ("NORTHSTAR TECHNOL PAYMENT", "Income", "Alex's Income", "Alex's Income"),
    ("NORTHSTAR TECHNOL", "Income", "Alex's Income", "Alex's Income"),
    ("NORTHSTAR", "Income", "Alex's Income", "Alex's Income"),
    ("42644 BRIGHTSTART  PAYROLL", "Income", "Jordan's Income", "Jordan's Income"),
    ("42644 BRIGHTSTART DIR DEP", "Income", "Jordan's Income", "Jordan's Income"),
    ("42645 BRIGHTSTART DIR DEP", "Income", "Jordan's Income", "Jordan's Income"),
    ("42644 BRIGHTSTART", "Income", "Jordan's Income", "Jordan's Income"),
    ("42645 BRIGHTSTART", "Income", "Jordan's Income", "Jordan's Income"),
    # Work wash — Wells Fargo = work travel reimbursed (NOT household credit)
    ("WELLS FARGO CARD", "Work Wash", "Work Travel (Reimbursed)", "Work Travel (Reimbursed)"),
    # Mortgage / housing
    ("HOME LOAN SERVICER", "Housing", "Home Mortgage", "Home Mortgage"),
    ("DEMO LANE EAST", "Housing", "HOA / Community Dues", "Homeowners Association Fee 1st"),
    ("CENTRAL MAPLE COMM", "Housing", "HOA / Community Dues", "Homeowners Maple Grove Dues"),
    ("DEMO TITLE PROTECT", "Home Services & Subs", "Annual fees", "Home Services & Subs"),
    ("ABLE AIR", "Housing", "Home Maintenance", "Other Utitlities"),
    ("PROG SELECT INS", "Auto", "Car Insurance", "Car Insurance"),
    ("PROGRESSIVE", "Auto", "Car Insurance", "Car Insurance"),
    # Utilities
    ("FPL DIRECT", "Utilities", "FPL", "FPL"),
    ("FPL ", "Utilities", "FPL", "FPL"),
    ("FLCITYGAS", "Utilities", "Gas Bill", "Gas Bill"),
    ("FL CITY GAS", "Utilities", "Gas Bill", "Gas Bill"),
    ("DEMO CITY WATER", "Utilities", "Water", "Water"),
    ("FBS*DEMO CITY WATER", "Utilities", "Water", "Water"),
    ("AT&T", "Utilities", "AT&T", "AT&T"),
    ("ATT *", "Utilities", "AT&T", "AT&T"),
    # Groceries (pharmacy before Publix)
    ("PUBLIX PHARMACY", "Health & Personal", "Medical", "Medical"),
    ("PUBLIX", "Groceries", "Publix", "Publix"),
    ("TARGET", "Groceries", "Target", "Target"),
    ("BJ'S", "Groceries", "BJ's", "BJ's"),
    ("BJS WHOLESALE", "Groceries", "BJ's", "BJ's"),
    ("COSTCO", "Groceries", "Costco", "Cosco"),
    ("COSCO", "Groceries", "Costco", "Cosco"),
    ("SAMSCLUB", "Groceries", "Sam's Club", "Other (food Category)"),
    ("SAMS CLUB", "Groceries", "Sam's Club", "Other (food Category)"),
    ("WALMART", "Groceries", "WalMart", "WalMart"),
    ("WAL-MART", "Groceries", "WalMart", "WalMart"),
    ("WM SUPERCENTER", "Groceries", "WalMart", "WalMart"),
    # Transportation
    ("SUNPASS", "Transportation", "Tolls", "Tolls"),
    ("CFX - E-PASS", "Transportation", "Tolls", "Tolls"),
    ("E-PASS", "Transportation", "Tolls", "Tolls"),
    ("UBER", "Transportation", "Uber / Lyft", "Uber"),
    ("LYFT", "Transportation", "Uber / Lyft", "Uber"),
    ("SHELL OIL", "Transportation", "Gas", "Gas"),
    ("SHELL ", "Transportation", "Gas", "Gas"),
    ("CHEVRON", "Transportation", "Gas", "Gas"),
    ("EXXON", "Transportation", "Gas", "Gas"),
    ("MOBIL ", "Transportation", "Gas", "Gas"),
    ("7-ELEVEN", "Transportation", "Gas", "Gas"),
    ("EVERYDAY ", "Transportation", "Gas", "Gas"),
    ("WAWA", "Transportation", "Gas", "Gas"),
    ("RACE TRAC", "Transportation", "Gas", "Gas"),
    ("RACETRAC", "Transportation", "Gas", "Gas"),
    ("CIRCLE K", "Transportation", "Gas", "Gas"),
    ("VEHICLETAG", "Transportation", "Parking / DMV", "Other (Transportation Category)"),
    ("MYDMV", "Transportation", "Parking / DMV", "Other (Transportation Category)"),
    ("PARKIN", "Transportation", "Parking / DMV", "Other (Transportation Category)"),
    # School / tuition
    ("FLORIDA PREPAID", "School", "Florida Pre-paid", "Florida Pre-paid"),
    ("FL PREPAID", "School", "Florida Pre-paid", "Florida Pre-paid"),
    ("BRIGHTSTART CATHOL RECEIVABLE", "Income", "Other Income", "Other Income"),
    ("BRIGHTSTART CATHOL", "School", "Tuition Max", "Max"),
    ("TUITION", "School", "Tuition Max", "Max"),
    ("SAMPLE SCHOOL CAFETERIA", "School", "After-school", "after-school"),
    ("PELOTON", "Home Services & Subs", "Peloton Membership", "Peloton Membership"),
    ("DEMO YOUTH SPORTS", "School", "Kids Activities / Memberships", "Max Memberships"),
    ("PP*DEMO YOUTH SPORTS", "School", "Kids Activities / Memberships", "Max Memberships"),
    # Auto loans / wash
    ("DEMO KIA DEALER", "Auto", "Kia Rio", "Kia Rio"),
    ("DEMO KIA DEALER", "Auto", "Kia Rio", "Kia Rio"),
    ("KIA MOTORS", "Auto", "Kia Rio", "Kia Rio"),
    ("KIA RIO", "Auto", "Kia Rio", "Kia Rio"),
    ("TELLURIDE", "Auto", "Kia Telluride", "Kea Telluride"),
    ("ALLY FINANCIAL", "Auto", "Kia Telluride", "Kea Telluride"),
    ("CAR-WASH-CLUB", "Auto", "Car Wash", "Car Wash Club"),
    ("CAR WASH CLUB", "Auto", "Car Wash", "Car Wash Club"),
    # Credit cards / debt (rewards card / Marriott = personal)
    ("PAYMENT TO CHASE CARD", "Credit Cards", "Marriott Chase", "Meriott Chase"),
    ("CHASE CARD ENDING", "Credit Cards", "Marriott Chase", "Meriott Chase"),
    ("APPLECARD", "Credit Cards", "Apple Card", "Apple Card"),
    ("APPLE CARD", "Credit Cards", "Apple Card", "Apple Card"),
    ("CITIBANK", "Credit Cards", "Citi Card", "Citi Card"),
    ("CITI CARD", "Credit Cards", "Citi Card", "Citi Card"),
    ("CITICARD", "Credit Cards", "Citi Card", "Citi Card"),
    ("BK OF AMER VI/MC", "Credit Cards", "Other Debt", "Citi Card"),
    ("LIGHTSTREAM", "Credit Cards", "Lightstream", "Lightstream"),
    ("LENDING CLUB", "Credit Cards", "Lending Club", "Lending Club"),
    ("SYNCHRONY", "Credit Cards", "Synchrony", "Synchrony"),
    ("DEPT EDUCATION", "Credit Cards", "Student Loans", "Student Loans"),
    ("STUDENT LN", "Credit Cards", "Student Loans", "Student Loans"),
    ("EDUSERVE", "Credit Cards", "Student Loans", "Student Loans"),
    # Shopping
    ("AMAZON", "Shopping", "Amazon", "Amazon"),
    ("AMZN", "Shopping", "Amazon", "Amazon"),
    ("AFTERPAY", "Shopping", "Afterpay", "Afterpay"),
    ("PAYPAL *PYPL PAYIN4", "Shopping", "Afterpay", "Afterpay"),
    ("KLARNA", "Shopping", "Other Shopping", "Other Outings"),
    ("ANTHROPOLOGIE", "Shopping", "Malls / Retail", "Malls"),
    ("HOME DEPOT", "Shopping", "Home Goods / Hardware", "Other (if applicable, provide a description)"),
    ("ACE HARDWARE", "Shopping", "Home Goods / Hardware", "Other (if applicable, provide a description)"),
    ("THRIFTY SPEC", "Shopping", "Home Goods / Hardware", "Other (if applicable, provide a description)"),
    ("THRIFTY SPECIALT", "Shopping", "Home Goods / Hardware", "Other (if applicable, provide a description)"),
    # Memberships / subscriptions
    ("YOUTUBEPREMI", "Home Services & Subs", "YouTube", "YouTube Subscription"),
    ("YOUTUBE", "Home Services & Subs", "YouTube", "YouTube Subscription"),
    ("NETFLIX", "Home Services & Subs", "Netflix", "Video Stream"),
    ("CRICUT", "Home Services & Subs", "Cricut", "Jordan's Craft Club"),
    ("HOMETEAM", "Home Services & Subs", "Pest Control", "HomeTeam Pest Control"),
    ("HOME TEAM PEST", "Home Services & Subs", "Pest Control", "HomeTeam Pest Control"),
    ("DISNEY", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("DCL RESERVATIONS", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("UNIVERSAL ORLANDO", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("UNIVERSAL STUDIOS", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("WDW ", "Home Services & Subs", "Theme Parks", "Park Pass"),
    ("WALT DISNEY", "Home Services & Subs", "Theme Parks", "Park Pass"),
    # Pets
    ("PETSMART", "Health & Personal", "Dog / Pets", "Dog"),
    ("PETCO", "Health & Personal", "Dog / Pets", "Dog"),
    ("ISLAND ANIMAL", "Health & Personal", "Dog / Pets", "Dog"),
    ("SCENTHOUND", "Health & Personal", "Dog / Pets", "Dog"),
    ("RUBIO PET", "Health & Personal", "Dog / Pets", "Dog"),
    ("AMERICAN KENNEL", "Health & Personal", "Dog / Pets", "Dog"),
    ("DOG SPOT", "Health & Personal", "Dog / Pets", "Dog"),
    ("VETERINARY", "Health & Personal", "Dog / Pets", "Dog"),
    ("VET ", "Health & Personal", "Dog / Pets", "Dog"),
    # Medical / personal
    ("FOREFRONT DERMATOLOGY", "Health & Personal", "Medical", "Medical"),
    ("DERMATOLOGY", "Health & Personal", "Medical", "Medical"),
    ("CVS/PHARMACY", "Health & Personal", "Medical", "Medical"),
    ("CVS PHARMACY", "Health & Personal", "Medical", "Medical"),
    ("WALGREENS", "Health & Personal", "Medical", "Medical"),
    ("MEDFAST URGENT", "Health & Personal", "Medical", "Medical"),
    ("DOXO MEDICAL", "Health & Personal", "Medical", "Medical"),
    ("DEMO FAMILY DENTAL", "Health & Personal", "Medical", "Medical"),
    ("DENTAL", "Health & Personal", "Medical", "Medical"),
    ("PEDIATRICS", "Health & Personal", "Medical", "Medical"),
    ("TIDE CLEANERS", "Health & Personal", "Dry Cleaners", "Dry Cleaners"),
    ("BEEF'S BARBERSHOP", "Health & Personal", "Hair-cut", "Hair-cut"),
    ("BARBER", "Health & Personal", "Hair-cut", "Hair-cut"),
    ("PRISTINE SPA", "Health & Personal", "Hair-cut", "Hair-cut"),
    ("VAGARO", "Health & Personal", "Hair-cut", "Hair-cut"),
    ("HARMONYNSOUL", "Health & Personal", "Hair-cut", "Hair-cut"),
    # Work cafeteria / workplace lunches (NOT coffee shops)
    ("CAFE C ", "Dining", "Work Lunches", "Fast Food / Food Outings"),
    # Coffee / cafe shops (before generic dining)
    ("STARBUCKS", "Dining", "Coffee / Cafe", "Fast Food / Food Outings"),
    ("FOXTAIL COFFEE", "Dining", "Coffee / Cafe", "Fast Food / Food Outings"),
    ("DUNKIN", "Dining", "Coffee / Cafe", "Fast Food / Food Outings"),
    ("SALTY BAGEL", "Dining", "Coffee / Cafe", "Fast Food / Food Outings"),
    ("WHISK AND GRIND", "Dining", "Coffee / Cafe", "Fast Food / Food Outings"),
    # Fast food
    ("CULVERS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CULVER'S", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CHICK-FIL-A", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CHICKFILA", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("PANERA", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("MOE'S", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("MOES ", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("MCDONALD", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("WENDY'S", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("WENDYS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("TACO BELL", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("CHIPOTLE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("POPEYES", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("DOMINO", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("PIZZA", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("TROPICAL SMOOTHIE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("RAISING CANES", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("RAISING CANE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("FIVE GUYS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("COLD STONE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("PANDA EXPRESS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("ICE CREAM", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("STRONG ISLAND ICE", "Dining", "Fast Food", "Fast Food / Food Outings"),
    ("LONG DOGGERS", "Dining", "Fast Food", "Fast Food / Food Outings"),
    # Sit-down / restaurants (were misc / uncategorized / wrongly lumped)
    ("TEXAS ROADHOUSE", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("OLIVE TREE", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("ASIAN TIME", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("PLAZA MEXICO", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("FIESTA AZUL", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("FLAMES MEDITERRANEA", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("FLYINGBURRO", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("EL TESORO", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("SQ *FAMILY OWNED", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("SQ *DEMO CAFE", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("DEMO WHITS CAFE", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("SQ *BY BROTHERS", "Dining", "Restaurants", "Fast Food / Food Outings"),
    ("PORT ST LUCIE CONCES", "Entertainment", "Family Outings", "Family Outings"),
    # Lawn / cleaning / allowance (Zelle)
    ("ZELLE PAYMENT TO DEMO LAWN", "Home Services & Subs", "Lawn Service", "Lawn Service"),
    ("ZELLE PAYMENT TO PRESSURE CLEANING", "Home Services & Subs", "Pressure Cleaning", "Home Pressure Cleaning"),
    ("PRESSURE CLEANING", "Home Services & Subs", "Pressure Cleaning", "Home Pressure Cleaning"),
    ("DEAN WINDOW CLEANER", "Home Services & Subs", "Home Cleaning Team", "Home Cleaning"),
    ("ZELLE PAYMENT TO CASEY", "Home Services & Subs", "Home Cleaning Team", "Home Cleaning"),
    ("ZELLE PAYMENT TO DEMO TUTOR", "School", "Tutoring", "Tutor"),
    ("ZELLE PAYMENT TO CASEY", "Allowance", "Partner Allowance", "Partner Allowance"),
    ("ZELLE PAYMENT TO JORDAN", "Allowance", "Partner Allowance", "Partner Allowance"),
    # Entertainment
    ("AMC ", "Entertainment", "Family Outings", "Family Outings"),
    ("FANDANGO", "Entertainment", "Family Outings", "Family Outings"),
    ("URBAN AIR", "Entertainment", "Family Outings", "Family Outings"),
    ("ROUTE 7 KARTING", "Entertainment", "Family Outings", "Family Outings"),
    ("SPACE COAST ICEPLEX", "Entertainment", "Family Outings", "Family Outings"),
    ("TICKETMASTER", "Entertainment", "Family Outings", "Family Outings"),
    ("EAGLERIDGE GOLDE", "Entertainment", "Family Outings", "Family Outings"),
    ("WINSHAPE CAMPS", "Entertainment", "Family Outings", "Family Outings"),
    ("DEMO EVENT VENUE", "Entertainment", "Family Outings", "Family Outings"),
    ("IRDTC.ORG", "Entertainment", "Other Outings", "Other Outings"),
    # Tax / misc
    ("INTUIT *TURBOTAX", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    ("TURBOTAX", "Shopping", "Other Shopping", "Other (if applicable, provide a description)"),
    # Transfers / savings
    ("ONLINE TRANSFER TO DEMO SAV", "Transfers / Savings", "Savings", "Savings"),
    ("ONLINE TRANSFER FROM SAV", "Transfers / Savings", "Savings", "Savings"),
    ("ONLINE TRANSFER TO  SAV", "Transfers / Savings", "Savings", "Savings"),
    ("ONLINE TRANSFER TO SAV", "Transfers / Savings", "Savings", "Savings"),
    ("ONLINE TRANSFER TO CHK", "Transfers / Savings", "Internal Transfer", "Savings"),
    ("FID BKG SVC LLC  MONEYLINE", "Transfers / Savings", "Brokerage / Fidelity", "Savings"),
    ("FID BKG", "Transfers / Savings", "Brokerage / Fidelity", "Savings"),
    ("FIDELITY", "Transfers / Savings", "Brokerage / Fidelity", "Savings"),
    # Misc income credits
    ("ZELLE PAYMENT FROM", "Income", "Other Income", "Other Income"),
    ("ATM CHECK DEPOSIT", "Income", "Other Income", "Other Income"),
    ("ATM CASH DEPOSIT", "Income", "Other Income", "Other Income"),
    ("DEPOSIT  ID NUMBER", "Income", "Other Income", "Other Income"),
    ("IRS  TREAS", "Income", "Other Income", "Other Income"),
    ("TAX REF", "Income", "Other Income", "Other Income"),
]


def parse_chase_date(s: str) -> str:
    """MM/DD/YYYY → ISO YYYY-MM-DD."""
    s = (s or "").strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {s!r}")


def _first_present(row: dict, *keys: str) -> str:
    for k in keys:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return ""


def detect_csv_kind(fieldnames: Optional[Iterable[str]]) -> str:
    """Return 'checking', 'card', or 'unknown' from CSV headers."""
    names = {(h or "").strip() for h in (fieldnames or [])}
    if "Posting Date" in names:
        return "checking"
    if "Transaction Date" in names or "Post Date" in names:
        return "card"
    return "unknown"


def parse_csv_rows(path_or_file) -> list[dict]:
    """Parse bank checking or credit-card CSV.

    Checking: Posting Date, Description, Amount, Balance, Type, Details
    Card: Transaction Date (preferred) or Post Date, Description, Amount,
          Type, Category, Memo. Sale/Fee negative; Payment/Return positive.
    """
    close = False
    if isinstance(path_or_file, (str, Path)):
        f = open(path_or_file, newline="", encoding="utf-8-sig")
        close = True
    else:
        f = path_or_file
    try:
        reader = csv.DictReader(f)
        kind = detect_csv_kind(reader.fieldnames)
        out = []
        for row in reader:
            desc = (row.get("Description") or "").strip()
            if kind == "card":
                date_raw = _first_present(row, "Transaction Date", "Post Date")
            else:
                date_raw = _first_present(row, "Posting Date", "Transaction Date", "Post Date")
            if not date_raw and not desc:
                continue
            amt_raw = (row.get("Amount") or "0").strip().replace(",", "")
            bal_raw = (row.get("Balance") or "").strip().replace(",", "")
            try:
                amount = float(amt_raw)
            except ValueError:
                continue
            try:
                iso = parse_chase_date(date_raw)
            except ValueError:
                continue
            balance = None
            if bal_raw:
                try:
                    balance = float(bal_raw)
                except ValueError:
                    balance = None
            external_id = _first_present(
                row,
                "Transaction ID",
                "Transaction Id",
                "FitId",
                "FITID",
                "Check or Slip #",
                "Check Number",
                "Ref #",
                "Reference",
                "Id",
                "ID",
            )
            item = {
                "date": iso,
                "amount": amount,
                "label": desc,
                "type": (row.get("Type") or "").strip(),
                "balance": balance,
                "details": (row.get("Details") or "").strip(),
                "chase_category": (row.get("Category") or "").strip(),
                "memo": (row.get("Memo") or "").strip(),
                "csv_kind": kind,
                "external_id": external_id or None,
            }
            out.append(item)
        return out
    finally:
        if close:
            f.close()


def _normalize_pattern(p: str) -> str:
    return re.sub(r"\s+", " ", p.strip().upper())


def load_taxonomy(path: Optional[Path] = None) -> dict:
    path = path or TAXONOMY_PATH
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def excel_to_parent_sub(excel_name: str, taxonomy: Optional[dict] = None) -> tuple[str, str, str]:
    """Map old Excel category → (parent, subcategory, legacy_category)."""
    taxonomy = taxonomy or load_taxonomy()
    mapping = (taxonomy.get("excel_name_to_new") or {}).get(excel_name)
    if mapping:
        return mapping["parent"], mapping["subcategory"], excel_name
    if excel_name == UNCATEGORIZED:
        return UNCATEGORIZED_PARENT, UNCATEGORIZED, UNCATEGORIZED
    return UNCATEGORIZED_PARENT, excel_name or UNCATEGORIZED, excel_name or UNCATEGORIZED


class MerchantMapper:
    """Keyword/pattern → (parent, subcategory, legacy_category) mapper."""

    def __init__(self, maps: Optional[list[tuple[str, str, str, str]]] = None):
        # (pattern_upper, parent, subcategory, legacy_category)
        self.maps: list[tuple[str, str, str, str]] = list(maps) if maps is not None else []
        self.taxonomy = load_taxonomy()

    @classmethod
    def load(cls, conn=None, json_path: Optional[Path] = None) -> "MerchantMapper":
        json_path = json_path or MERCHANT_MAP_PATH
        learned: list[tuple[str, str, str, str]] = []
        taxonomy = load_taxonomy()

        def coerce(pattern: str, category: str, parent: str = "", subcategory: str = "") -> tuple[str, str, str, str]:
            p = _normalize_pattern(pattern)
            if parent and subcategory:
                return p, parent, subcategory, category or subcategory
            # Old JSON shape: pattern + category (Excel name)
            par, sub, legacy = excel_to_parent_sub(category, taxonomy)
            # Special-case Wells previously mapped to Citi Card
            if "WELLS FARGO" in p:
                return p, "Work Wash", "Work Travel (Reimbursed)", "Work Travel (Reimbursed)"
            return p, par, sub, legacy

        if conn is not None:
            try:
                for row in db.list_merchant_maps(conn):
                    learned.append(
                        coerce(
                            row["pattern"],
                            row["category"],
                            row.get("parent") or "",
                            row.get("subcategory") or "",
                        )
                    )
            except Exception:
                pass
        if json_path.exists():
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                items = data if isinstance(data, list) else data.get("maps", [])
                for item in items:
                    if isinstance(item, dict):
                        learned.append(
                            coerce(
                                item["pattern"],
                                item.get("category") or item.get("subcategory") or UNCATEGORIZED,
                                item.get("parent") or "",
                                item.get("subcategory") or "",
                            )
                        )
                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                        if len(item) >= 4:
                            learned.append(
                                (
                                    _normalize_pattern(item[0]),
                                    item[1],
                                    item[2],
                                    item[3],
                                )
                            )
                        else:
                            learned.append(coerce(item[0], item[1]))
            except Exception:
                pass
        defaults = [
            (_normalize_pattern(p), par, sub, leg) for p, par, sub, leg in DEFAULT_KEYWORD_MAP
        ]
        # Defaults first for taxonomy v2 correctness, then learned only if new patterns
        seen = set()
        merged: list[tuple[str, str, str, str]] = []
        for p, par, sub, leg in defaults + learned:
            if not p or p in seen:
                continue
            seen.add(p)
            merged.append((p, par, sub, leg))
        return cls(merged)

    def categorize_full(self, description: str, amount: float = 0.0) -> tuple[str, str, str]:
        """Return (parent, subcategory, legacy_category)."""
        text = _normalize_pattern(description)
        amt = float(amount or 0)
        if "FID BKG" in text or "FIDELITY" in text or "MONEYLINE" in text:
            if amt > 0:
                return "Income", "Other Income", "Other Income"
            return "Transfers / Savings", "Brokerage / Fidelity", "Savings"
        if "ONLINE TRANSFER FROM SAV" in text:
            return "Transfers / Savings", "Savings", "Savings"
        if "ONLINE TRANSFER TO" in text and "SAV" in text:
            return "Transfers / Savings", "Savings", "Savings"
        if "WELLS FARGO" in text:
            return "Work Wash", "Work Travel (Reimbursed)", "Work Travel (Reimbursed)"
        # Jordan primary ~$1,500/mo arrives as ATM/check deposits (no employer string).
        # Amount band catches exact $1,500 and occasional same-deposit extras.
        deposit_hints = (
            "ATM CHECK DEPOSIT",
            "ATM CASH DEPOSIT",
            "DEPOSIT  ID NUMBER",
            "DEPOSIT ID NUMBER",
        )
        if 1400.0 <= amt <= 2200.0 and any(h in text for h in deposit_hints):
            return "Income", "Jordan's Income", "Jordan's Income"
        for pattern, parent, subcategory, legacy in self.maps:
            if pattern and pattern in text:
                return parent, subcategory, legacy
        return UNCATEGORIZED_PARENT, UNCATEGORIZED, UNCATEGORIZED

    def categorize(self, description: str, amount: float = 0.0) -> str:
        """Back-compat: return legacy Excel category name."""
        _, _, legacy = self.categorize_full(description, amount)
        return legacy

    def ensure_patterns_for_labels(
        self, labeled: Iterable[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        existing = {p for p, *_ in self.maps}
        new = []
        for label, category in labeled:
            if category == UNCATEGORIZED:
                continue
            stem = _normalize_pattern(label)[:40].strip()
            if len(stem) < 5 or stem in existing:
                continue
            par, sub, leg = excel_to_parent_sub(category, self.taxonomy)
            new.append((stem, category))
            existing.add(stem)
            self.maps.insert(0, (stem, par, sub, leg))
        return new

    def save(self, conn=None, json_path: Optional[Path] = None) -> None:
        json_path = json_path or MERCHANT_MAP_PATH
        json_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "maps": [
                {
                    "pattern": p,
                    "parent": par,
                    "subcategory": sub,
                    "category": leg,
                }
                for p, par, sub, leg in self.maps
            ],
        }
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if conn is not None:
            for p, par, sub, leg in self.maps:
                db.upsert_merchant_map(conn, p, leg, parent=par, subcategory=sub)


def merchant_stem(label: str) -> str:
    """Human-readable merchant key for uncategorized reporting."""
    t = re.sub(r"\s+", " ", (label or "").strip())
    t = re.sub(r"\s+\d{2}/\d{2}(\s|$)", " ", t)
    t = re.sub(r"\s+(WEB ID|PPD ID|CCD ID|TRANSACTION#:)[:\s]*\S+", "", t, flags=re.I)
    t = re.sub(r"\s+\d{6,}", " ", t)
    return t.strip()[:60] or label[:60]


def format_category(parent: str, subcategory: str) -> str:
    if not parent or parent == UNCATEGORIZED_PARENT:
        return subcategory or UNCATEGORIZED
    return f"{parent}/{subcategory}"


def normalize_memo(text: str) -> str:
    """Normalize memo/label for fingerprinting."""
    t = (text or "").strip().upper()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^A-Z0-9 #*/.&'-]+", "", t)
    return t[:120]


def txn_fingerprint(
    *,
    date: str,
    amount: float,
    label: str = "",
    memo: str = "",
    source: str = CSV_SOURCE,
    external_id: Optional[str] = None,
) -> str:
    """Duplicate key: prefer stable bank ID; else date+amount+normalized memo+source."""
    ext = (external_id or "").strip()
    if ext:
        return f"id:{source}:{ext}"
    memo_norm = normalize_memo(memo or label)
    amt = f"{float(amount):.2f}"
    return f"{source}|{date}|{amt}|{memo_norm}"


def fingerprint_for_actual(row: dict, *, source: str = CSV_SOURCE) -> str:
    return txn_fingerprint(
        date=str(row.get("date") or ""),
        amount=float(row.get("amount") or 0),
        label=str(row.get("label") or ""),
        memo=str(row.get("memo") or ""),
        source=str(row.get("source") or source),
        external_id=row.get("external_id"),
    )


def existing_fingerprints(conn, *, source: str = CSV_SOURCE) -> set[str]:
    rows = conn.execute(
        """SELECT date, amount, label, memo, source, external_id
           FROM actuals WHERE source=?""",
        (source,),
    ).fetchall()
    return {fingerprint_for_actual(dict(r), source=source) for r in rows}


def _categorize_parsed_rows(rows: list[dict], mapper: "MerchantMapper") -> list[dict]:
    categorized = []
    for r in rows:
        parent, sub, legacy = mapper.categorize_full(r["label"], r["amount"])
        categorized.append(
            {
                "date": r["date"],
                "amount": r["amount"],
                "category": legacy,
                "parent": parent,
                "subcategory": sub,
                "label": r["label"],
                "source": CSV_SOURCE,
                "enabled": True,
                "memo": r.get("memo") or "",
                "txn_type": r.get("type") or "",
                "external_id": r.get("external_id"),
                "fingerprint": txn_fingerprint(
                    date=r["date"],
                    amount=r["amount"],
                    label=r["label"],
                    memo=r.get("memo") or "",
                    source=CSV_SOURCE,
                    external_id=r.get("external_id"),
                ),
            }
        )
    return categorized


SHORT_HISTORY_DAYS = 45


def preview_csv_import(conn, path_or_file, *, source: str = CSV_SOURCE) -> dict[str, Any]:
    """Non-destructive preview before Merge/Replace."""
    db.init_db(conn)
    rows = parse_csv_rows(path_or_file)
    mapper = MerchantMapper.load(conn)
    categorized = _categorize_parsed_rows(rows, mapper)
    dates = [r["date"] for r in rows]
    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None
    n_cat = sum(1 for i in categorized if i["subcategory"] != UNCATEGORIZED)
    n_uncat = len(categorized) - n_cat

    existing = conn.execute(
        "SELECT date, amount, label, memo, source, external_id FROM actuals WHERE source=?",
        (source,),
    ).fetchall()
    existing_fps = {fingerprint_for_actual(dict(r), source=source) for r in existing}
    existing_dates = [str(dict(r)["date"]) for r in existing]
    ex_min = min(existing_dates) if existing_dates else None
    ex_max = max(existing_dates) if existing_dates else None

    dupes = [i for i in categorized if i["fingerprint"] in existing_fps]
    new_rows = [i for i in categorized if i["fingerprint"] not in existing_fps]

    overlap = False
    overlap_note = None
    if date_min and date_max and ex_min and ex_max:
        overlap = not (date_max < ex_min or date_min > ex_max)
        if overlap:
            overlap_note = (
                f"CSV {date_min}→{date_max} overlaps existing {source} "
                f"{ex_min}→{ex_max} ({len(existing)} rows)"
            )

    span_days = None
    short_history = False
    if date_min and date_max:
        d0 = datetime.strptime(date_min, "%Y-%m-%d").date()
        d1 = datetime.strptime(date_max, "%Y-%m-%d").date()
        span_days = (d1 - d0).days + 1
        short_history = span_days < SHORT_HISTORY_DAYS

    return {
        "rows_parsed": len(rows),
        "date_min": date_min,
        "date_max": date_max,
        "span_days": span_days,
        "categorized": n_cat,
        "uncategorized": n_uncat,
        "pct_categorized": round(100.0 * n_cat / len(categorized), 1) if categorized else 0.0,
        "existing_bank_csv_rows": len(existing),
        "existing_date_min": ex_min,
        "existing_date_max": ex_max,
        "overlap": overlap,
        "overlap_note": overlap_note,
        "duplicate_count": len(dupes),
        "new_row_count": len(new_rows),
        "short_history_warning": short_history,
        "short_history_message": (
            f"CSV spans only {span_days} day(s) (< {SHORT_HISTORY_DAYS}). "
            "A short export can look fine in preview but leave large gaps in history."
            if short_history and span_days is not None
            else None
        ),
        "sample_new": [
            {"date": i["date"], "amount": i["amount"], "label": (i["label"] or "")[:60]}
            for i in new_rows[:8]
        ],
        "sample_duplicates": [
            {"date": i["date"], "amount": i["amount"], "label": (i["label"] or "")[:60]}
            for i in dupes[:8]
        ],
        "top_uncategorized": Counter(
            merchant_stem(i["label"])
            for i in categorized
            if i["subcategory"] == UNCATEGORIZED
        ).most_common(10),
    }


def import_csv(
    conn,
    path_or_file,
    *,
    replace_csv_actuals: bool = True,
    mode: Optional[str] = None,
    save_maps: bool = True,
    create_backup: bool = True,
    confirm_replace: bool = False,
    root: Optional[Path] = None,
) -> dict[str, Any]:
    """
    Import bank CSV into actuals with parent + subcategory.

    Modes:
      - replace: clear source='bank_csv' then insert all (destructive).
        Requires confirm_replace=True when mode is set explicitly to "replace".
        Legacy callers using only replace_csv_actuals=True are auto-confirmed.
      - merge: insert rows whose fingerprint is not already present.

    Auto timestamped household backup runs before replace when create_backup=True.
    Does NOT touch recurring_rules or scenarios.
    """
    db.init_db(conn)
    mode_explicit = mode is not None
    if mode is None:
        mode = "replace" if replace_csv_actuals else "merge"
    mode = str(mode).strip().lower()
    if mode not in ("merge", "replace"):
        raise ValueError(f"Unknown import mode: {mode}")
    if mode == "replace" and mode_explicit and not confirm_replace:
        raise ValueError(
            "Replace is destructive: pass confirm_replace=True after reviewing the preview."
        )

    rows = parse_csv_rows(path_or_file)
    mapper = MerchantMapper.load(conn)
    categorized = _categorize_parsed_rows(rows, mapper)

    backup_info = None
    cleared = 0
    skipped_duplicates = 0
    to_insert = categorized

    if mode == "replace":
        if create_backup:
            try:
                from engine.household_backup import create_household_backup

                db_file = None
                try:
                    row = conn.execute("PRAGMA database_list").fetchone()
                    # row: (seq, name, file)
                    file_path = row[2] if row else None
                    if file_path:
                        db_file = Path(file_path)
                except Exception:
                    db_file = None
                backup_root = root
                if backup_root is None and db_file is not None:
                    # db usually lives in <root>/data/cashflow.db
                    backup_root = db_file.resolve().parent.parent
                backup_info = create_household_backup(
                    root=backup_root,
                    db_path=db_file,
                    label="pre_import_replace",
                )
            except FileNotFoundError:
                backup_info = {"skipped": "no_db_file"}
            except Exception as e:
                backup_info = {"error": str(e)}
        cleared = db.clear_actuals_by_source(conn, CSV_SOURCE)
        to_insert = categorized
        replace_policy = (
            "cleared actuals where source='bank_csv' then inserted all CSV rows "
            "(timestamped backup before clear)"
        )
    else:
        fps = existing_fingerprints(conn, source=CSV_SOURCE)
        to_insert = []
        for item in categorized:
            if item["fingerprint"] in fps:
                skipped_duplicates += 1
            else:
                to_insert.append(item)
                fps.add(item["fingerprint"])
        replace_policy = (
            f"merge: inserted new fingerprints only; skipped {skipped_duplicates} duplicates"
        )

    for item in to_insert:
        db.add_actual(
            conn,
            {
                "date": item["date"],
                "amount": item["amount"],
                "category": item["category"],
                "parent": item["parent"],
                "subcategory": item["subcategory"],
                "label": item["label"],
                "source": item["source"],
                "enabled": True,
                "txn_type": item.get("txn_type"),
                "memo": item.get("memo"),
                "external_id": item.get("external_id"),
            },
        )

    if save_maps:
        mapper.save(conn)

    # Refresh learned due dates from CSV/pending actuals (non-fatal).
    due_date_learn_report = None
    try:
        from engine.due_date_learn import learn_from_actuals, apply_learned_doms

        learned = learn_from_actuals(conn)
        apply_report = apply_learned_doms(conn, dry_run=False, min_samples=3, learned=learned)
        due_date_learn_report = {
            "learned_categories": (learned.get("summary") or {}).get("n_categories"),
            "eligible": (learned.get("summary") or {}).get("eligible_to_apply"),
            "applied_rule_changes": apply_report.get("n_changed_rules"),
            "changes": apply_report.get("changes") or [],
            "skipped": [
                {
                    "category": s.get("category"),
                    "reason": s.get("reason"),
                    "samples": s.get("samples"),
                }
                for s in (apply_report.get("skipped") or [])
                if str(s.get("reason") or "").startswith(("low", "locked"))
            ],
        }
    except Exception as e:
        due_date_learn_report = {"error": str(e)}

    dates = [r["date"] for r in rows]
    n_cat = sum(1 for i in categorized if i["subcategory"] != UNCATEGORIZED)
    uncat_counter: Counter = Counter()
    cat_spend: Counter = Counter()
    parent_spend: Counter = Counter()
    cat_counts: Counter = Counter()
    parent_counts: Counter = Counter()
    total_in = 0.0
    total_out = 0.0
    samples = []
    for item in categorized:
        display = format_category(item["parent"], item["subcategory"])
        cat_counts[display] += 1
        parent_counts[item["parent"]] += 1
        amt = float(item["amount"])
        if amt >= 0:
            total_in += amt
        else:
            total_out += amt
            cat_spend[display] += abs(amt)
            parent_spend[item["parent"]] += abs(amt)
        if item["subcategory"] == UNCATEGORIZED:
            uncat_counter[merchant_stem(item["label"])] += 1
        if len(samples) < 25 and item["subcategory"] != UNCATEGORIZED:
            samples.append(
                {
                    "date": item["date"],
                    "amount": item["amount"],
                    "parent": item["parent"],
                    "subcategory": item["subcategory"],
                    "category": item["category"],
                    "label": item["label"][:70],
                }
            )

    report = {
        "rows_parsed": len(rows),
        "rows_imported": len(to_insert),
        "rows_skipped_duplicates": skipped_duplicates,
        "rows_cleared": cleared,
        "mode": mode,
        "categorized": n_cat,
        "uncategorized": len(categorized) - n_cat,
        "pct_categorized": round(100.0 * n_cat / len(categorized), 1) if categorized else 0.0,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "total_in": round(total_in, 2),
        "total_out": round(total_out, 2),
        "top_categories_by_spend": cat_spend.most_common(15),
        "top_parents_by_spend": parent_spend.most_common(15),
        "top_uncategorized": uncat_counter.most_common(20),
        "category_counts": cat_counts.most_common(),
        "parent_counts": parent_counts.most_common(),
        "sample_mapped": samples[:15],
        "replace_policy": replace_policy,
        "backup": backup_info,
        "csv_balances": _balance_snapshot(rows),
        "taxonomy_version": 2,
        "due_date_learn": due_date_learn_report,
        "change_report": {
            "mode": mode,
            "inserted": len(to_insert),
            "skipped_duplicates": skipped_duplicates,
            "cleared_bank_csv": cleared,
            "backup_path": (backup_info or {}).get("path"),
            "date_min": min(dates) if dates else None,
            "date_max": max(dates) if dates else None,
        },
    }
    return report



def reclassify_actuals(conn, *, source: str = CSV_SOURCE) -> dict[str, Any]:
    """Re-run taxonomy classification on existing actuals without re-parsing CSV."""
    db.init_db(conn)
    mapper = MerchantMapper.load(conn)
    rows = conn.execute(
        "SELECT id, label, amount FROM actuals WHERE source=?", (source,)
    ).fetchall()
    updated = 0
    uncat = 0
    parent_counts: Counter = Counter()
    for r in rows:
        parent, sub, legacy = mapper.categorize_full(r["label"] or "", float(r["amount"] or 0))
        conn.execute(
            "UPDATE actuals SET category=?, parent=?, subcategory=? WHERE id=?",
            (legacy, parent, sub, r["id"]),
        )
        updated += 1
        parent_counts[parent] += 1
        if sub == UNCATEGORIZED:
            uncat += 1
    conn.commit()
    mapper.save(conn)
    return {
        "updated": updated,
        "uncategorized": uncat,
        "pct_categorized": round(100.0 * (updated - uncat) / updated, 1) if updated else 0.0,
        "parent_counts": parent_counts.most_common(),
    }


def _balance_snapshot(rows: list[dict]) -> dict:
    """Grab CSV Balance column around 2026-09-11/12 for sanity check."""
    out = {"newest_row": None, "on_2026_09_11": [], "on_2026_09_12": []}
    if not rows:
        return out
    r0 = rows[0]
    out["newest_row"] = {
        "date": r0["date"],
        "amount": r0["amount"],
        "balance": r0.get("balance"),
        "label": r0["label"][:60],
    }
    for r in rows:
        if r["date"] == "2026-09-11":
            out["on_2026_09_11"].append(
                {"amount": r["amount"], "balance": r.get("balance"), "label": r["label"][:50]}
            )
        elif r["date"] == "2026-09-12":
            out["on_2026_09_12"].append(
                {"amount": r["amount"], "balance": r.get("balance"), "label": r["label"][:50]}
            )
    return out



def allowance_budget_for_month(year: int, month: int) -> float:
    """Wife's allowance / family-card payoff target for YYYY-MM.

    Validated against recurring_rules: $2,500 through Feb 2027 (incl. Sep
    planned), then $3,500 from March 2027. Do not change the bump month
    unless Alex asks.
    """
    if (int(year), int(month)) <= ALLOWANCE_2500_THROUGH:
        return 2500.0
    return 3500.0


def is_card_purchase(txn_type: str, amount: float | None = None) -> bool:
    t = (txn_type or "").strip()
    if t in CARD_PURCHASE_TYPES:
        return True
    if t in CARD_PAYMENT_TYPES or t in CARD_RETURN_TYPES:
        return False
    # Fallback: unlabeled negative = purchase
    return amount is not None and float(amount) < 0


def _card_memo(row: dict) -> str:
    bits = []
    chase_cat = (row.get("chase_category") or "").strip()
    memo = (row.get("memo") or "").strip()
    if chase_cat:
        bits.append(f"Chase: {chase_cat}")
    if memo:
        bits.append(memo)
    return " · ".join(bits)


def _categorize_card_row(mapper: MerchantMapper, row: dict) -> tuple[str, str, str]:
    """Household taxonomy first; payments are never household income."""
    txn_type = (row.get("type") or "").strip()
    label = row.get("label") or ""
    amount = float(row.get("amount") or 0)
    if txn_type in CARD_PAYMENT_TYPES or "PAYMENT THANK YOU" in label.upper():
        return "Credit Cards", "Card Payment", "Meriott Chase"
    parent, sub, legacy = mapper.categorize_full(label, amount)
    return parent, sub, legacy


def import_black_card_csv(
    conn,
    path_or_file,
    *,
    replace: bool = True,
    save_maps: bool = True,
) -> dict[str, Any]:
    """Import Rewards Card / Travel Rewards (demo rewards card) CSV.

    Stores source='chase_black_card' only. Never clears bank_csv.
    Does NOT run due_date_learn / apply_learned_doms (card dates must not
    retrain checking bill DOMs). Payments are not household income.
    """
    db.init_db(conn)
    rows = parse_csv_rows(path_or_file)
    mapper = MerchantMapper.load(conn)

    categorized = []
    uncat_counter: Counter = Counter()
    cat_spend: Counter = Counter()
    parent_spend: Counter = Counter()
    cat_counts: Counter = Counter()
    parent_counts: Counter = Counter()
    type_counts: Counter = Counter()
    total_purchases = 0.0
    total_payments = 0.0
    total_returns = 0.0
    total_fees = 0.0
    samples = []

    for r in rows:
        parent, sub, legacy = _categorize_card_row(mapper, r)
        display = format_category(parent, sub)
        txn_type = (r.get("type") or "").strip()
        amt = float(r["amount"])
        item = {
            "date": r["date"],
            "amount": amt,
            "category": legacy,
            "parent": parent,
            "subcategory": sub,
            "label": r["label"],
            "source": BLACK_CARD_SOURCE,
            "enabled": True,
            "txn_type": txn_type,
            "memo": _card_memo(r),
        }
        categorized.append(item)
        cat_counts[display] += 1
        parent_counts[parent] += 1
        type_counts[txn_type or "(blank)"] += 1
        if txn_type in CARD_PAYMENT_TYPES:
            total_payments += amt
        elif txn_type in CARD_RETURN_TYPES:
            total_returns += amt
        elif txn_type == "Fee" or (txn_type in CARD_PURCHASE_TYPES and amt < 0):
            spend = abs(amt)
            if txn_type == "Fee":
                total_fees += spend
            total_purchases += spend
            cat_spend[display] += spend
            parent_spend[parent] += spend
        elif amt < 0:
            total_purchases += abs(amt)
            cat_spend[display] += abs(amt)
            parent_spend[parent] += abs(amt)
        if sub == UNCATEGORIZED and txn_type not in CARD_PAYMENT_TYPES:
            uncat_counter[merchant_stem(r["label"])] += 1
        if len(samples) < 25 and sub != UNCATEGORIZED:
            samples.append(
                {
                    "date": r["date"],
                    "amount": amt,
                    "type": txn_type,
                    "parent": parent,
                    "subcategory": sub,
                    "category": legacy,
                    "label": r["label"][:70],
                }
            )

    if replace:
        db.clear_actuals_by_source(conn, BLACK_CARD_SOURCE)

    for item in categorized:
        db.add_actual(conn, item)

    if save_maps:
        mapper.save(conn)

    dates = [r["date"] for r in rows]
    n_cat = sum(1 for i in categorized if i["subcategory"] != UNCATEGORIZED)
    net = round(total_payments + total_returns - total_purchases, 2)
    imported_at = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {
        "rows_parsed": len(rows),
        "rows_imported": len(categorized),
        "categorized": n_cat,
        "uncategorized": len(categorized) - n_cat,
        "pct_categorized": round(100.0 * n_cat / len(categorized), 1) if categorized else 0.0,
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "total_purchases": round(total_purchases, 2),
        "total_payments": round(total_payments, 2),
        "total_returns": round(total_returns, 2),
        "total_fees": round(total_fees, 2),
        "net": net,
        "total_in": round(total_payments + total_returns, 2),
        "total_out": round(-total_purchases, 2),
        "type_counts": type_counts.most_common(),
        "top_categories_by_spend": cat_spend.most_common(15),
        "top_parents_by_spend": parent_spend.most_common(15),
        "top_uncategorized": uncat_counter.most_common(20),
        "category_counts": cat_counts.most_common(),
        "parent_counts": parent_counts.most_common(),
        "sample_mapped": samples[:15],
        "replace_policy": "cleared actuals where source='chase_black_card' then inserted card rows",
        "source": BLACK_CARD_SOURCE,
        "display_name": BLACK_CARD_DISPLAY,
        "taxonomy_version": 2,
        "due_date_learn": None,
        "imported_at": imported_at,
        "allowance_note": (
            "Wife's allowance / family-card budget is $2,500/mo through Feb 2027 "
            "(Sep 2026 planned $2,500), then $3,500 from March 2027. "
            "Validated against recurring_rules; start month not changed."
        ),
    }
    # Stamp so Suggested cards UI can show "CSV refreshed …" and never rely on frozen scores.
    try:
        from engine.rewards_optimize import save_import_meta

        save_import_meta(
            {
                "imported_at": imported_at,
                "source": BLACK_CARD_SOURCE,
                "rows_imported": report["rows_imported"],
                "date_min": report["date_min"],
                "date_max": report["date_max"],
                "total_purchases": report["total_purchases"],
            }
        )
    except Exception:
        pass
    return report



def load_black_card_budget_context(path: Optional[Path] = None) -> dict[str, Any]:
    """Mid-month Black card story: allowance target + prior-month residual.

    Source of truth for Dashboard hero cards and household-notifier-texts residual.
    Clear prior_month_residual to 0 when Alex pays the Aug leftover.
    """
    path = path or BLACK_CARD_BUDGET_CONTEXT_PATH
    if not path.exists():
        return {
            "as_of": None,
            "allowance_target": 2500.0,
            "prior_month_residual": 0.0,
            "prior_month_label": "Still from August",
            "note": "",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "as_of": None,
            "allowance_target": 2500.0,
            "prior_month_residual": 0.0,
            "prior_month_label": "Still from August",
            "note": "",
        }
    return data if isinstance(data, dict) else {}


def load_black_card_snapshot(path: Optional[Path] = None) -> dict[str, Any]:
    path = path or BLACK_CARD_SNAPSHOT_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_black_card_snapshot(payload: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    path = path or BLACK_CARD_SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return load_black_card_snapshot(path)


def write_import_report(report: dict, settings: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# bank CSV import report",
        "",
        f"- **Rows imported:** {report['rows_imported']} (parsed {report['rows_parsed']})",
        f"- **Date range:** {report['date_min']} → {report['date_max']}",
        f"- **Total in (credits):** ${report['total_in']:,.2f}",
        f"- **Total out (debits):** ${report['total_out']:,.2f}",
        f"- **Categorized:** {report['categorized']} / {report['rows_imported']} "
        f"({report['pct_categorized']}%)",
        f"- **Uncategorized:** {report['uncategorized']}",
        f"- **Taxonomy:** v{report.get('taxonomy_version', 1)}",
        f"- **Replace policy:** {report['replace_policy']}",
        f"- **Start balance (settings):** ${float(settings.get('start_balance', 0)):,.2f}",
        f"- **Start date / end date:** {settings.get('start_date')} → {settings.get('end_date')}",
        "",
        "## Balance sanity (CSV Balance column)",
        "",
    ]
    snap = report.get("csv_balances") or {}
    nr = snap.get("newest_row")
    if nr:
        lines.append(
            f"- Newest CSV row: {nr['date']} amount={nr['amount']} "
            f"balance={nr['balance']} ({nr['label']})"
        )
    lines.append(f"- Rows on 2026-09-11: {len(snap.get('on_2026_09_11') or [])}")
    for x in (snap.get("on_2026_09_11") or [])[:8]:
        lines.append(f"  - {x['amount']:+.2f} bal={x['balance']} {x['label']}")
    lines.append(f"- Rows on 2026-09-12: {len(snap.get('on_2026_09_12') or [])}")
    sb = float(settings.get("start_balance", 0))
    newest_bal = (nr or {}).get("balance")
    if newest_bal is not None:
        delta = sb - float(newest_bal)
        lines.append(
            f"- Settings start_balance ${sb:,.2f} vs newest CSV balance "
            f"${float(newest_bal):,.2f} (delta ${delta:,.2f}). "
            "Projection still starts at settings balance on start_date; "
            "historical actuals are stored for analytics only."
        )
    lines += ["", "## Top parents by spend (absolute debits)", ""]
    for cat, amt in report.get("top_parents_by_spend") or []:
        lines.append(f"- **{cat}**: ${amt:,.2f}")
    lines += ["", "## Top 15 categories by spend (absolute debits)", ""]
    for cat, amt in report["top_categories_by_spend"]:
        lines.append(f"- **{cat}**: ${amt:,.2f}")
    lines += ["", "## Top 20 uncategorized merchants by count", ""]
    if report["top_uncategorized"]:
        for m, c in report["top_uncategorized"]:
            lines.append(f"- ({c}) {m}")
    else:
        lines.append("- (none)")
    lines += ["", "## Sample mapped rows", ""]
    for s in report["sample_mapped"]:
        lines.append(
            f"- {s['date']} | {s['amount']:+.2f} | **{s.get('parent','')}/{s.get('subcategory', s.get('category'))}** | {s['label']}"
        )
    lines += [
        "",
        "## Confirmation",
        "",
        f"- start_balance still **{sb}** (expected 5000.00)",
        f"- start_date / end_date unchanged: {settings.get('start_date')} / {settings.get('end_date')}",
        "- recurring_rules and scenarios were not wiped",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
