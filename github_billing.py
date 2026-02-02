"""
GitHub Enterprise Billing Report Generator
==========================================

A production-ready automation script for generating monthly GitHub Enterprise
billing reports broken down by product.

Supports both Enterprise and Organization level billing.
Updated for GitHub's 2024 Billing API changes.

Author: Cloud FinOps Engineering
Version: 2.1.0
"""

import os
import sys
import json
import csv
import logging
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from collections import defaultdict
import time

import yaml
import requests

# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class UsageMetric:
    """Represents a single usage metric for billing."""
    product: str
    sku: str
    date: str
    usage_quantity: Decimal
    unit: str
    unit_price: Decimal
    gross_cost: Decimal
    discount_amount: Decimal
    net_cost: Decimal
    organization: Optional[str] = None
    repository: Optional[str] = None


@dataclass
class ProductSummary:
    """Aggregated summary for a product."""
    product: str
    total_gross: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    total_net: Decimal = Decimal("0")
    sku_breakdown: Dict[str, Dict[str, Decimal]] = field(default_factory=dict)

    def add_sku(self, sku: str, gross: Decimal, discount: Decimal, net: Decimal, qty: Decimal, unit: str):
        if sku not in self.sku_breakdown:
            self.sku_breakdown[sku] = {"gross": Decimal("0"), "discount": Decimal("0"), "net": Decimal("0"), "qty": Decimal("0"), "unit": unit}
        self.sku_breakdown[sku]["gross"] += gross
        self.sku_breakdown[sku]["discount"] += discount
        self.sku_breakdown[sku]["net"] += net
        self.sku_breakdown[sku]["qty"] += qty


@dataclass
class BillingReport:
    """Complete billing report for a period."""
    name: str  # Enterprise or Organization name
    level: str  # "enterprise" or "organization"
    billing_month: str
    generated_at: str
    currency: str
    metrics: List[UsageMetric] = field(default_factory=list)
    product_summaries: Dict[str, ProductSummary] = field(default_factory=dict)
    total_gross: Decimal = Decimal("0")
    total_discount: Decimal = Decimal("0")
    total_net: Decimal = Decimal("0")

    def add_metric(self, metric: UsageMetric):
        """Add a metric and update totals."""
        self.metrics.append(metric)
        self.total_gross += metric.gross_cost
        self.total_discount += metric.discount_amount
        self.total_net += metric.net_cost

        # Update product summary
        if metric.product not in self.product_summaries:
            self.product_summaries[metric.product] = ProductSummary(product=metric.product)

        summary = self.product_summaries[metric.product]
        summary.total_gross += metric.gross_cost
        summary.total_discount += metric.discount_amount
        summary.total_net += metric.net_cost
        summary.add_sku(metric.sku, metric.gross_cost, metric.discount_amount, metric.net_cost, metric.usage_quantity, metric.unit)


# =============================================================================
# GitHub API Client
# =============================================================================

class GitHubAPIClient:
    """GitHub API client with rate limiting and error handling."""

    BASE_URL = "https://api.github.com"

    def __init__(self, token: str):
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        })

    def _handle_rate_limit(self, response: requests.Response) -> bool:
        """Handle GitHub API rate limiting."""
        remaining = int(response.headers.get("X-RateLimit-Remaining", 1))
        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))

        if remaining == 0:
            wait_time = max(reset_time - time.time(), 0) + 1
            self.logger.warning(f"Rate limit hit. Waiting {wait_time:.0f} seconds...")
            time.sleep(wait_time)
            return True
        return False

    def get(self, endpoint: str, params: Dict = None) -> Dict[str, Any]:
        """Make a GET request."""
        url = f"{self.BASE_URL}{endpoint}"
        max_retries = 3

        for attempt in range(max_retries):
            try:
                response = self.session.get(url, params=params)

                if response.status_code == 403 and self._handle_rate_limit(response):
                    continue

                response.raise_for_status()
                return response.json() if response.text else {}

            except requests.exceptions.HTTPError as e:
                if response.status_code == 404:
                    self.logger.warning(f"Resource not found: {endpoint}")
                    return {}
                if response.status_code == 410:
                    self.logger.warning(f"Endpoint deprecated: {endpoint}")
                    return {}
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        return {}


# =============================================================================
# Billing Data Collector
# =============================================================================

class BillingCollector:
    """Collect billing data using GitHub's billing API."""

    def __init__(self, client: GitHubAPIClient, config: Dict[str, Any]):
        self.client = client
        self.config = config
        self.logger = logging.getLogger(__name__)

    def collect_usage(self, name: str, level: str, billing_month: str) -> List[UsageMetric]:
        """Collect usage data from the billing API."""
        metrics = []

        # Build endpoint based on level
        if level == "enterprise":
            endpoint = f"/enterprises/{name}/settings/billing/usage"
        else:
            endpoint = f"/orgs/{name}/settings/billing/usage"

        self.logger.info(f"Fetching billing usage for {level}: {name}")

        data = self.client.get(endpoint)

        if not data or "usageItems" not in data:
            self.logger.warning("No usage data returned from API")
            return metrics

        usage_items = data.get("usageItems", [])
        self.logger.info(f"Retrieved {len(usage_items)} usage line items")

        # Filter by billing month if specified
        target_month = billing_month if billing_month != "current" else datetime.now().strftime("%Y-%m")

        for item in usage_items:
            item_date = item.get("date", "")[:7]  # Extract YYYY-MM

            if target_month and item_date != target_month:
                continue

            metric = UsageMetric(
                product=item.get("product", "unknown"),
                sku=item.get("sku", "unknown"),
                date=item.get("date", "")[:10],
                usage_quantity=Decimal(str(item.get("quantity", 0))).quantize(Decimal("0.01")),
                unit=item.get("unitType", ""),
                unit_price=Decimal(str(item.get("pricePerUnit", 0))),
                gross_cost=Decimal(str(item.get("grossAmount", 0))).quantize(Decimal("0.01")),
                discount_amount=Decimal(str(item.get("discountAmount", 0))).quantize(Decimal("0.01")),
                net_cost=Decimal(str(item.get("netAmount", 0))).quantize(Decimal("0.01")),
                organization=item.get("organizationName") or None,
                repository=item.get("repositoryName") or None
            )
            metrics.append(metric)

        return metrics

    def collect_copilot(self, name: str, level: str) -> Dict[str, Any]:
        """Collect Copilot billing data."""
        self.logger.info("Fetching Copilot billing...")

        if level == "enterprise":
            endpoint = f"/enterprises/{name}/copilot/billing"
        else:
            endpoint = f"/orgs/{name}/copilot/billing"

        data = self.client.get(endpoint)

        if data:
            breakdown = data.get("seat_breakdown", {})
            return {
                "total_seats": data.get("total_seats", breakdown.get("total", 0)),
                "active_seats": breakdown.get("active_this_cycle", 0),
                "inactive_seats": breakdown.get("inactive_this_cycle", 0),
                "pending_invitation": breakdown.get("pending_invitation", 0),
                "pending_cancellation": breakdown.get("pending_cancellation", 0),
                "seat_management": data.get("seat_management_setting", "unknown")
            }

        return {}


# =============================================================================
# Report Generator
# =============================================================================

class ReportGenerator:
    """Generate billing reports in multiple formats."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.output_config = config.get("output", {})
        self.logger = logging.getLogger(__name__)

    def generate(self, report: BillingReport, copilot_data: Dict = None):
        """Generate reports in all configured formats."""
        formats = self.output_config.get("formats", ["console"])
        output_dir = Path(self.output_config.get("directory", "./reports"))
        output_dir.mkdir(parents=True, exist_ok=True)

        prefix = self.output_config.get("filename_prefix", "github-billing")
        filename_base = f"{prefix}-{report.name}-{report.billing_month}"

        for fmt in formats:
            if fmt == "console":
                self._generate_console(report, copilot_data)
            elif fmt == "csv":
                # Summary CSV
                summary_path = output_dir / f"{filename_base}-summary.csv"
                self._generate_summary_csv(report, summary_path)
                self.logger.info(f"Summary CSV saved: {summary_path}")
                # Detailed CSV
                detail_path = output_dir / f"{filename_base}-detailed.csv"
                self._generate_detailed_csv(report, detail_path)
                self.logger.info(f"Detailed CSV saved: {detail_path}")
            elif fmt == "json":
                # Summary JSON
                summary_path = output_dir / f"{filename_base}-summary.json"
                self._generate_summary_json(report, copilot_data, summary_path)
                self.logger.info(f"Summary JSON saved: {summary_path}")
                # Detailed JSON
                detail_path = output_dir / f"{filename_base}-detailed.json"
                self._generate_detailed_json(report, copilot_data, detail_path)
                self.logger.info(f"Detailed JSON saved: {detail_path}")

    def _generate_console(self, report: BillingReport, copilot_data: Dict = None):
        """Generate human-readable console output."""
        level_display = report.level.upper()

        print("\n" + "=" * 100)
        print(f"GITHUB {level_display} BILLING REPORT")
        print("=" * 100)
        print(f"{report.level.capitalize()}:  {report.name}")
        print(f"Billing Month:  {report.billing_month}")
        print(f"Generated:      {report.generated_at}")
        print(f"Currency:       {report.currency}")
        print("-" * 100)

        # =====================================================================
        # SUMMARY SECTION
        # =====================================================================
        print(f"\n{'=' * 100}")
        print(f"{'PRODUCT SUMMARY (Executive View)':^100}")
        print(f"{'=' * 100}")
        print(f"{'Product':<25} {'Gross Cost':>18} {'Discount':>18} {'Net Cost':>18} {'% of Total':>15}")
        print("-" * 100)

        for product, summary in sorted(report.product_summaries.items(), key=lambda x: x[1].total_net, reverse=True):
            pct = (summary.total_net / report.total_net * 100) if report.total_net > 0 else Decimal("0")
            print(
                f"{product:<25} "
                f"${summary.total_gross:>16,.2f} "
                f"${summary.total_discount:>16,.2f} "
                f"${summary.total_net:>16,.2f} "
                f"{pct:>14.1f}%"
            )

        print("-" * 100)
        print(
            f"{'TOTAL':<25} "
            f"${report.total_gross:>16,.2f} "
            f"${report.total_discount:>16,.2f} "
            f"${report.total_net:>16,.2f} "
            f"{'100.0%':>15}"
        )
        print("=" * 100)

        # Effective discount rate
        if report.total_gross > 0:
            discount_rate = (report.total_discount / report.total_gross * 100)
            print(f"\nEffective Discount Rate: {discount_rate:.2f}%")

        # =====================================================================
        # SKU BREAKDOWN SECTION
        # =====================================================================
        print(f"\n{'=' * 100}")
        print(f"{'SKU BREAKDOWN (Detailed View)':^100}")
        print(f"{'=' * 100}")
        print(f"{'Product':<18} {'SKU':<40} {'Quantity':>15} {'Net Cost':>15}")
        print("-" * 100)

        for product, summary in sorted(report.product_summaries.items()):
            first_row = True
            for sku, data in sorted(summary.sku_breakdown.items(), key=lambda x: x[1]["net"], reverse=True):
                if data["net"] == 0 and data["gross"] == 0:
                    continue  # Skip zero-cost items
                product_display = product if first_row else ""
                sku_display = sku[:38] + ".." if len(sku) > 40 else sku
                print(
                    f"{product_display:<18} "
                    f"{sku_display:<40} "
                    f"{data['qty']:>13,.2f} "
                    f"${data['net']:>13,.2f}"
                )
                first_row = False
            if not first_row:
                print("-" * 100)

        # =====================================================================
        # COPILOT SECTION
        # =====================================================================
        if copilot_data and copilot_data.get("total_seats", 0) > 0:
            print(f"\n{'=' * 100}")
            print(f"{'COPILOT SEATS':^100}")
            print(f"{'=' * 100}")
            print(f"Total Seats:          {copilot_data.get('total_seats', 0):,}")
            print(f"Active This Cycle:    {copilot_data.get('active_seats', 0):,}")
            print(f"Inactive This Cycle:  {copilot_data.get('inactive_seats', 0):,}")
            print(f"Pending Invitation:   {copilot_data.get('pending_invitation', 0):,}")
            print(f"Pending Cancellation: {copilot_data.get('pending_cancellation', 0):,}")
            print(f"Seat Management:      {copilot_data.get('seat_management', 'N/A')}")
            print("=" * 100)

    def _generate_summary_csv(self, report: BillingReport, filepath: Path):
        """Generate summary CSV with product-level totals only."""
        fieldnames = ["product", "gross_cost", "discount_amount", "net_cost", "percent_of_total"]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for product, summary in sorted(report.product_summaries.items(), key=lambda x: x[1].total_net, reverse=True):
                pct = float(summary.total_net / report.total_net * 100) if report.total_net > 0 else 0
                writer.writerow({
                    "product": product,
                    "gross_cost": float(summary.total_gross),
                    "discount_amount": float(summary.total_discount),
                    "net_cost": float(summary.total_net),
                    "percent_of_total": round(pct, 2)
                })

            # Totals row
            writer.writerow({
                "product": "TOTAL",
                "gross_cost": float(report.total_gross),
                "discount_amount": float(report.total_discount),
                "net_cost": float(report.total_net),
                "percent_of_total": 100.0
            })

    def _generate_detailed_csv(self, report: BillingReport, filepath: Path):
        """Generate detailed CSV with all line items."""
        fieldnames = [
            "date", "product", "sku", "organization", "repository",
            "quantity", "unit", "unit_price", "gross_cost",
            "discount_amount", "net_cost"
        ]

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for metric in report.metrics:
                writer.writerow({
                    "date": metric.date,
                    "product": metric.product,
                    "sku": metric.sku,
                    "organization": metric.organization or "",
                    "repository": metric.repository or "",
                    "quantity": float(metric.usage_quantity),
                    "unit": metric.unit,
                    "unit_price": float(metric.unit_price),
                    "gross_cost": float(metric.gross_cost),
                    "discount_amount": float(metric.discount_amount),
                    "net_cost": float(metric.net_cost)
                })

            # Totals row
            writer.writerow({
                "date": "",
                "product": "TOTAL",
                "sku": "",
                "organization": "",
                "repository": "",
                "quantity": "",
                "unit": "",
                "unit_price": "",
                "gross_cost": float(report.total_gross),
                "discount_amount": float(report.total_discount),
                "net_cost": float(report.total_net)
            })

    def _generate_summary_json(self, report: BillingReport, copilot_data: Dict, filepath: Path):
        """Generate summary JSON with product-level totals."""
        output = {
            "metadata": {
                "name": report.name,
                "level": report.level,
                "billing_month": report.billing_month,
                "generated_at": report.generated_at,
                "currency": report.currency,
                "report_type": "summary",
                "report_version": "2.1"
            },
            "totals": {
                "gross_cost": float(report.total_gross),
                "discount": float(report.total_discount),
                "net_cost": float(report.total_net),
                "effective_discount_rate": float(
                    report.total_discount / report.total_gross * 100
                ) if report.total_gross > 0 else 0
            },
            "products": {},
            "copilot_seats": copilot_data or {}
        }

        for product, summary in report.product_summaries.items():
            pct = float(summary.total_net / report.total_net * 100) if report.total_net > 0 else 0
            output["products"][product] = {
                "gross_cost": float(summary.total_gross),
                "discount": float(summary.total_discount),
                "net_cost": float(summary.total_net),
                "percent_of_total": round(pct, 2)
            }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)

    def _generate_detailed_json(self, report: BillingReport, copilot_data: Dict, filepath: Path):
        """Generate detailed JSON with all line items."""
        output = {
            "metadata": {
                "name": report.name,
                "level": report.level,
                "billing_month": report.billing_month,
                "generated_at": report.generated_at,
                "currency": report.currency,
                "report_type": "detailed",
                "report_version": "2.1"
            },
            "totals": {
                "gross_cost": float(report.total_gross),
                "discount": float(report.total_discount),
                "net_cost": float(report.total_net),
                "line_item_count": len(report.metrics)
            },
            "product_summaries": {},
            "line_items": [],
            "copilot_seats": copilot_data or {}
        }

        for product, summary in report.product_summaries.items():
            output["product_summaries"][product] = {
                "gross_cost": float(summary.total_gross),
                "discount": float(summary.total_discount),
                "net_cost": float(summary.total_net),
                "sku_breakdown": {
                    sku: {
                        "gross_cost": float(data["gross"]),
                        "discount": float(data["discount"]),
                        "net_cost": float(data["net"]),
                        "quantity": float(data["qty"]),
                        "unit": data["unit"]
                    }
                    for sku, data in summary.sku_breakdown.items()
                }
            }

        for metric in report.metrics:
            output["line_items"].append({
                "date": metric.date,
                "product": metric.product,
                "sku": metric.sku,
                "organization": metric.organization,
                "repository": metric.repository,
                "usage": {
                    "quantity": float(metric.usage_quantity),
                    "unit": metric.unit
                },
                "pricing": {
                    "unit_price": float(metric.unit_price),
                    "gross_cost": float(metric.gross_cost)
                },
                "discount_amount": float(metric.discount_amount),
                "net_cost": float(metric.net_cost)
            })

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2)


# =============================================================================
# Main Orchestrator
# =============================================================================

class GitHubBillingReport:
    """Main orchestrator for GitHub billing report generation."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        self._setup_logging()
        self.logger = logging.getLogger(__name__)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        config_file = Path(config_path)

        if not config_file.exists():
            return {
                "billing": {"month": "current", "currency": "USD"},
                "output": {"directory": "./reports", "formats": ["console", "csv", "json"]}
            }

        with open(config_file, 'r') as f:
            return yaml.safe_load(f)

    def _setup_logging(self):
        """Configure logging."""
        log_config = self.config.get("logging", {})
        level = getattr(logging, log_config.get("level", "INFO").upper())

        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[logging.StreamHandler()]
        )

    def run(self, name: str, token: str, level: str = "enterprise", billing_month: str = "current") -> BillingReport:
        """Execute the billing report generation."""
        self.logger.info(f"Starting GitHub Billing Report generation for {level}: {name}")

        # Determine billing month
        if billing_month == "current":
            today = datetime.now()
            first_of_month = today.replace(day=1)
            last_month = first_of_month - timedelta(days=1)
            billing_month = last_month.strftime("%Y-%m")
            self.logger.info(f"Using previous month for complete data: {billing_month}")

        # Initialize API client
        client = GitHubAPIClient(token)

        # Create report
        report = BillingReport(
            name=name,
            level=level,
            billing_month=billing_month,
            generated_at=datetime.now().isoformat(),
            currency=self.config.get("billing", {}).get("currency", "USD")
        )

        # Collect billing data
        collector = BillingCollector(client, self.config)

        # Get usage data
        metrics = collector.collect_usage(name, level, billing_month)
        for metric in metrics:
            report.add_metric(metric)

        self.logger.info(f"Collected {len(metrics)} usage metrics")
        self.logger.info(f"Total gross: ${report.total_gross:,.2f}")
        self.logger.info(f"Total discount: ${report.total_discount:,.2f}")
        self.logger.info(f"Total net: ${report.total_net:,.2f}")

        # Get Copilot data
        copilot_data = collector.collect_copilot(name, level)

        # Generate reports
        generator = ReportGenerator(self.config)
        generator.generate(report, copilot_data)

        self.logger.info("Billing report generation complete")

        return report


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GitHub Billing Report Generator (v2.1 - Enterprise & Org Support)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enterprise billing
  python github_billing.py --enterprise sidlabs --month 2026-01

  # Organization billing
  python github_billing.py --org octodemo --month 2026-01

  # Specify output formats
  python github_billing.py --enterprise sidlabs --format all
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--enterprise", "-e",
        help="GitHub Enterprise slug"
    )
    group.add_argument(
        "--org", "-o",
        help="GitHub Organization name"
    )

    parser.add_argument(
        "--month", "-m",
        default="current",
        help="Billing month (YYYY-MM or 'current' for previous month)"
    )

    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to configuration file"
    )

    parser.add_argument(
        "--format", "-f",
        choices=["console", "csv", "json", "all"],
        default="all",
        help="Output format"
    )

    parser.add_argument(
        "--output-dir",
        default="./reports",
        help="Output directory for reports"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Get token
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Error: GITHUB_TOKEN environment variable not set", file=sys.stderr)
        sys.exit(1)

    # Determine level and name
    if args.enterprise:
        level = "enterprise"
        name = args.enterprise
    else:
        level = "organization"
        name = args.org

    try:
        reporter = GitHubBillingReport(args.config)

        if args.debug:
            logging.getLogger().setLevel(logging.DEBUG)

        if args.output_dir:
            reporter.config.setdefault("output", {})["directory"] = args.output_dir

        if args.format == "all":
            reporter.config.setdefault("output", {})["formats"] = ["console", "csv", "json"]
        else:
            reporter.config.setdefault("output", {})["formats"] = [args.format]

        report = reporter.run(name, token, level, args.month)
        sys.exit(0)

    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
