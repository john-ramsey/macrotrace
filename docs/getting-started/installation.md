# Installation

## Requirements

MacroTrace requires Python 3.11 or higher.

## Install from PyPI

```bash
pip install macrotrace
```

## Development Installation

To install from source for development:

```bash
git clone <repository-url>
cd macrotrace
pip install -e ".[dev,docs]"
```

## API Keys / Environment Setup

### FRED (Federal Reserve Economic Data)

1. Register for a free API key at [https://fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html)
2. Set your API key as an environment variable:

```bash
export FRED_API_KEY='your_api_key_here'
```

### ONS (Office for National Statistics)

ONS data is publicly accessible and doesn't require an API key.
