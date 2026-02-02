# GitHub Enterprise Billing Report Generator

Generate monthly billing reports for GitHub Enterprise with product-level cost breakdown for Finance, FinOps, and leadership review.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Authentication Setup](#authentication-setup)
4. [Running Locally](#running-locally)
5. [GitHub Actions Setup](#github-actions-setup)
6. [Output Reports](#output-reports)
7. [Configuration Options](#configuration-options)
8. [API Reference](#api-reference)
9. [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd GH-Billing

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your GitHub token
export GITHUB_TOKEN="ghp_your_token_here"

# 4. Run for your enterprise
python github_billing.py --enterprise your-enterprise-slug --month 2026-01
```

That's it! Reports will be generated in the `./reports` directory.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.9+ | Check with `python --version` |
| pip | Latest | Check with `pip --version` |
| GitHub Token | - | With enterprise billing permissions |

### Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `requests` - HTTP client for GitHub API
- `PyYAML` - Configuration file parsing

---

## Authentication Setup

You need a GitHub Personal Access Token (PAT) with billing permissions.

### Step 1: Create a Fine-Grained PAT

1. Go to **GitHub.com** → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens**
2. Click **Generate new token**
3. Configure:
   - **Token name**: `billing-report`
   - **Expiration**: 90 days (recommended)
   - **Resource owner**: Select your **Enterprise**
   - **Repository access**: No repositories needed

4. Set **Permissions**:

   | Permission | Access Level |
   |------------|--------------|
   | **Organization permissions** → Billing | Read |
   | **Organization permissions** → Members | Read |
   | **Enterprise permissions** → Billing | Read |

5. Click **Generate token** and copy it immediately

### Step 2: Set the Token

**Option A: Environment Variable (Recommended)**

```bash
# Linux/macOS
export GITHUB_TOKEN="ghp_xxxxxxxxxxxxxxxxxxxx"

# Windows PowerShell
$env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"

# Windows CMD
set GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
```

**Option B: For GitHub Actions (see below)**

Store in repository secrets.

---

## Running Locally

### Basic Usage

```bash
# Enterprise billing report for a specific month
python github_billing.py --enterprise <enterprise-slug> --month 2026-01

# Organization billing report
python github_billing.py --org <org-name> --month 2026-01

# Use "current" for previous month (complete billing data)
python github_billing.py --enterprise <enterprise-slug> --month current
```

### Finding Your Enterprise Slug

Your enterprise slug is in the URL when you visit your enterprise:

```
https://github.com/enterprises/YOUR-ENTERPRISE-SLUG
                              ^^^^^^^^^^^^^^^^^^^^
                              This is your slug
```

### Command Line Options

| Option | Short | Description | Example |
|--------|-------|-------------|---------|
| `--enterprise` | `-e` | Enterprise slug **(required for enterprise)** | `--enterprise sidlabs` |
| `--org` | `-o` | Organization name **(required for org)** | `--org octodemo` |
| `--month` | `-m` | Billing month (YYYY-MM or "current") | `--month 2026-01` |
| `--format` | `-f` | Output format: console, csv, json, all | `--format all` |
| `--output-dir` | | Directory for output files | `--output-dir ./reports` |
| `--debug` | | Enable verbose logging | `--debug` |
| `--config` | `-c` | Path to config file | `--config config.yaml` |

### Examples

```bash
# Example 1: Enterprise billing for January 2026
python github_billing.py --enterprise sidlabs --month 2026-01

# Example 2: Organization billing with all output formats
python github_billing.py --org octodemo --month 2026-01 --format all

# Example 3: Console output only (no files)
python github_billing.py --enterprise sidlabs --format console

# Example 4: Custom output directory
python github_billing.py --enterprise sidlabs --output-dir /path/to/reports

# Example 5: Debug mode for troubleshooting
python github_billing.py --enterprise sidlabs --debug
```

### Sample Console Output

```
====================================================================================================
GITHUB ENTERPRISE BILLING REPORT
====================================================================================================
Enterprise:  sidlabs
Billing Month:  2026-01
Generated:      2026-02-02T10:42:59
Currency:       USD
----------------------------------------------------------------------------------------------------

====================================================================================================
                                  PRODUCT SUMMARY (Executive View)
====================================================================================================
Product                           Gross Cost           Discount           Net Cost      % of Total
----------------------------------------------------------------------------------------------------
copilot                   $           77.41 $           12.00 $           65.42          100.0%
actions                   $            0.33 $            0.33 $            0.00            0.0%
----------------------------------------------------------------------------------------------------
TOTAL                     $           77.74 $           12.33 $           65.42          100.0%
====================================================================================================

Effective Discount Rate: 15.86%
```

---

## GitHub Actions Setup

Automate monthly billing reports with GitHub Actions.

### Step 1: Create Repository Secrets

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **New repository secret**
3. Add:

   | Secret Name | Value |
   |-------------|-------|
   | `GITHUB_BILLING_TOKEN` | Your GitHub PAT with billing permissions |

### Step 2: Create Repository Variables

1. In the same page, click the **Variables** tab
2. Click **New repository variable**
3. Add:

   | Variable Name | Value |
   |---------------|-------|
   | `GITHUB_ENTERPRISE` | Your enterprise slug (e.g., `sidlabs`) |

### Step 3: Create the Workflow File

Create `.github/workflows/billing-report.yml`:

```yaml
name: Monthly Billing Report

on:
  # Run on the 1st of every month at 6 AM UTC
  schedule:
    - cron: '0 6 1 * *'

  # Allow manual runs
  workflow_dispatch:
    inputs:
      billing_month:
        description: 'Billing month (YYYY-MM or "current")'
        required: false
        default: 'current'
        type: string

jobs:
  generate-report:
    name: Generate Billing Report
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Determine billing month
        id: month
        run: |
          if [ "${{ github.event.inputs.billing_month }}" != "" ] && [ "${{ github.event.inputs.billing_month }}" != "current" ]; then
            echo "value=${{ github.event.inputs.billing_month }}" >> $GITHUB_OUTPUT
          else
            echo "value=$(date -d 'last month' +'%Y-%m')" >> $GITHUB_OUTPUT
          fi

      - name: Generate billing report
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_BILLING_TOKEN }}
        run: |
          python github_billing.py \
            --enterprise ${{ vars.GITHUB_ENTERPRISE }} \
            --month ${{ steps.month.outputs.value }} \
            --format all \
            --output-dir ./reports

      - name: Upload reports as artifact
        uses: actions/upload-artifact@v4
        with:
          name: billing-reports-${{ steps.month.outputs.value }}
          path: ./reports/
          retention-days: 90

      - name: Display summary
        run: |
          echo "## Billing Report Generated" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "**Enterprise:** ${{ vars.GITHUB_ENTERPRISE }}" >> $GITHUB_STEP_SUMMARY
          echo "**Month:** ${{ steps.month.outputs.value }}" >> $GITHUB_STEP_SUMMARY
          echo "" >> $GITHUB_STEP_SUMMARY
          echo "### Summary" >> $GITHUB_STEP_SUMMARY
          echo "\`\`\`" >> $GITHUB_STEP_SUMMARY
          cat ./reports/*-summary.csv >> $GITHUB_STEP_SUMMARY
          echo "\`\`\`" >> $GITHUB_STEP_SUMMARY
```

### Step 4: Run the Workflow

**Automatic Run:**
- The workflow runs automatically on the 1st of every month at 6 AM UTC

**Manual Run:**
1. Go to **Actions** tab in your repository
2. Select **Monthly Billing Report** workflow
3. Click **Run workflow**
4. (Optional) Enter a specific billing month (e.g., `2026-01`)
5. Click **Run workflow**

### Step 5: Download Reports

1. Go to **Actions** → Select the completed workflow run
2. Scroll to **Artifacts**
3. Download `billing-reports-YYYY-MM`

---

## Output Reports

The script generates **two types of reports** in each format:

### Summary Reports (For Finance/Leadership)

Simple product-level totals for executive review.

**`github-billing-{name}-{month}-summary.csv`**
```csv
product,gross_cost,discount_amount,net_cost,percent_of_total
copilot,77.41,12.0,65.42,100.0
actions,0.33,0.33,0.0,0.0
TOTAL,77.74,12.33,65.42,100.0
```

**`github-billing-{name}-{month}-summary.json`**
```json
{
  "metadata": {
    "name": "sidlabs",
    "level": "enterprise",
    "billing_month": "2026-01",
    "report_type": "summary"
  },
  "totals": {
    "gross_cost": 77.74,
    "discount": 12.33,
    "net_cost": 65.42,
    "effective_discount_rate": 15.86
  },
  "products": {
    "copilot": {
      "gross_cost": 77.41,
      "discount": 12.0,
      "net_cost": 65.42,
      "percent_of_total": 100.0
    }
  }
}
```

### Detailed Reports (For FinOps/Engineering)

Full line-item breakdown with dates, organizations, repositories, and SKUs.

**`github-billing-{name}-{month}-detailed.csv`**
```csv
date,product,sku,organization,repository,quantity,unit,unit_price,gross_cost,discount_amount,net_cost
2026-01-01,copilot,Copilot Business,,,1.0,UserMonths,19.0,19.0,0.0,19.0
2026-01-01,copilot,Copilot Premium Request,sidlabs-platform,,985.36,Requests,0.04,39.41,12.0,27.42
2026-01-02,actions,Actions Linux,sidlabs-platform,charm-api-decoder,10.0,Minutes,0.006,0.06,0.06,0.0
```

### Report Columns Explained

| Column | Description |
|--------|-------------|
| `date` | Usage date |
| `product` | GitHub product (actions, copilot, packages, etc.) |
| `sku` | Specific SKU (e.g., "Actions Linux", "Copilot Business") |
| `organization` | Organization within enterprise |
| `repository` | Repository name (for Actions/Packages) |
| `quantity` | Usage amount |
| `unit` | Unit type (Minutes, UserMonths, Requests, GB, etc.) |
| `unit_price` | Price per unit |
| `gross_cost` | Cost before discounts |
| `discount_amount` | Discount applied |
| `net_cost` | Final billed amount |

---

## Configuration Options

### Optional: config.yaml

Create a `config.yaml` file for default settings:

```yaml
# Billing settings
billing:
  currency: "USD"

# Output settings
output:
  directory: "./reports"
  formats:
    - "console"
    - "csv"
    - "json"
  filename_prefix: "github-billing"

# Logging
logging:
  level: "INFO"  # DEBUG, INFO, WARNING, ERROR
```

---

## API Reference

### GitHub API Endpoints Used

| Endpoint | Purpose |
|----------|---------|
| `GET /enterprises/{enterprise}/settings/billing/usage` | Enterprise billing data |
| `GET /orgs/{org}/settings/billing/usage` | Organization billing data |
| `GET /enterprises/{enterprise}/copilot/billing` | Copilot seat information |
| `GET /orgs/{org}/copilot/billing` | Org-level Copilot info |

### Products Reported

| Product | SKU Examples | Unit |
|---------|--------------|------|
| `actions` | Actions Linux, Actions Windows, Actions macOS | Minutes |
| `copilot` | Copilot Business, Copilot Enterprise, Premium Requests | UserMonths, Requests |
| `packages` | Packages storage, Packages data transfer | GB |
| `codespaces` | Codespaces compute, Codespaces storage | Core-hours, GB |
| `git_lfs` | Git LFS storage, Git LFS bandwidth | GB |
| `spark` | Spark Premium Request | Requests |

---

## Troubleshooting

### Error: "GITHUB_TOKEN environment variable not set"

**Solution:** Set your token before running:

```bash
export GITHUB_TOKEN="ghp_your_token_here"
```

### Error: "Resource not found" (404)

**Possible causes:**
1. Wrong enterprise slug - check the URL: `github.com/enterprises/YOUR-SLUG`
2. Token doesn't have enterprise billing permissions
3. You're not an enterprise admin

**Solution:** Verify your enterprise slug and token permissions.

### Error: "Forbidden" (403)

**Possible causes:**
1. Token lacks required scopes
2. SSO not authorized for the token
3. IP allowlist blocking access

**Solution:**
1. Regenerate token with correct permissions
2. Authorize SSO: GitHub → Settings → Personal access tokens → Configure SSO

### No data returned

**Possible causes:**
1. Wrong billing month format
2. No usage in the specified month

**Solution:** Use `YYYY-MM` format (e.g., `2026-01`) or `current`.

### Debug Mode

Run with `--debug` for detailed logging:

```bash
python github_billing.py --enterprise sidlabs --debug
```

This shows:
- API requests and responses
- Rate limit status
- Data processing details

---

## File Structure

```
GH-Billing/
├── github_billing.py          # Main script
├── config.yaml                # Configuration (optional)
├── requirements.txt           # Python dependencies
├── README.md                  # This file
├── .github/
│   └── workflows/
│       └── billing-report.yml # GitHub Actions workflow
└── reports/                   # Generated reports (created automatically)
    ├── github-billing-{name}-{month}-summary.csv
    ├── github-billing-{name}-{month}-summary.json
    ├── github-billing-{name}-{month}-detailed.csv
    └── github-billing-{name}-{month}-detailed.json
```

---

## Support

For issues:
1. Check [Troubleshooting](#troubleshooting) above
2. Run with `--debug` flag
3. Verify token permissions
4. Check GitHub API status: https://www.githubstatus.com/

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 2.1.0 | 2026-02 | Enterprise & org support, summary + detailed reports |
| 2.0.0 | 2026-02 | Updated for GitHub's new billing API |
| 1.0.0 | 2026-02 | Initial release |
