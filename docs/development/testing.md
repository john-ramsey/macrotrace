# Testing

MacroTrace uses pytest for testing.

## Running Tests

### All Tests

```bash
pytest
```

### With Coverage

```bash
pytest --cov=macrotrace --cov-report=html
```

View coverage report:
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

### Specific Tests

```bash
# Run tests in a specific file
pytest tests/models/test_db_models.py

# Run a specific test
pytest tests/models/test_db_models.py::test_dataset_creation

# Run tests matching a pattern
pytest -k "fred"
```

### Verbose Output

```bash
pytest -v
```

## Test Structure

Tests are organized by module:

```
tests/
├── models/              # Model tests
│   ├── test_db_models.py
│   └── mt/
│       ├── test_metadata.py
│       └── series/
│           └── test_series.py
└── sources/            # Source connector tests
    ├── base/
    ├── fred/
    └── ons/
```

## Writing Tests

### Basic Test

```python
import pytest
from macrotrace.models import Dataset

def test_dataset_creation():
    """Test creating a dataset."""
    dataset = Dataset.create(
        source='FRED',
        dataset_id='TEST123',
        name='Test Dataset'
    )

    assert dataset.source == 'FRED'
    assert dataset.dataset_id == 'TEST123'
    assert dataset.name == 'Test Dataset'
```

### Using Fixtures

```python
import pytest
from macrotrace.models import Dataset, Series

@pytest.fixture
def sample_dataset():
    """Create a sample dataset for testing."""
    return Dataset.create(
        source='FRED',
        dataset_id='GDPC1'
    )

def test_series_creation(sample_dataset):
    """Test creating a series with a fixture."""
    series = Series.create(
        dataset=sample_dataset,
        series_key={'series_id': 'GDPC1'}
    )

    assert series.dataset == sample_dataset
```

### Testing API Calls

Use mocking for API tests:

```python
import pytest
from unittest.mock import Mock, patch
from macrotrace.sources.fred import FREDAPIClient

@patch('macrotrace.sources.fred.requests.get')
def test_api_call(mock_get):
    """Test API call with mocked response."""
    # Setup mock
    mock_response = Mock()
    mock_response.json.return_value = {
        'series': {'id': 'GDPC1'}
    }
    mock_get.return_value = mock_response

    # Test
    client = FREDAPIClient()
    result = client.get_series('GDPC1')

    assert result['series']['id'] == 'GDPC1'
```

### Database Tests

Use transactions to keep tests isolated:

```python
import pytest
from macrotrace.models.db import db

@pytest.fixture(autouse=True)
def reset_database():
    """Reset database before each test."""
    with db.atomic() as transaction:
        yield
        transaction.rollback()
```

## Test Coverage

Current test coverage focuses on:
- Database models
- Data source connectors
- Manager classes
- Core business logic

Areas excluded from coverage (see `pyproject.toml`):
- `tests/*` (test files themselves)
- `macrotrace/sources/example.py` (example code)

## Continuous Integration

The full test suite runs automatically via GitHub Actions
(`.github/workflows/ci.yml`) on:

- Pull requests targeting `main`
- Pushes to `main`

The matrix covers Python 3.11, 3.12, and 3.13 on both Ubuntu and macOS.
Tests must pass on every cell of the matrix before a PR can be merged.

> Python 3.14 is not yet in the matrix because `torch` (a transitive
> dependency via `darts`) does not ship `cp314` wheels at the time of
> writing.

## Best Practices

1. **One assertion per test** (when possible)
2. **Use descriptive test names** that explain what is being tested
3. **Test both success and failure cases**
4. **Use fixtures** to avoid code duplication
5. **Mock external dependencies** (APIs, databases)
6. **Keep tests fast** - slow tests discourage running them

## Debugging Tests

```bash
# Drop into debugger on failure
pytest --pdb

# Show print statements
pytest -s

# Stop on first failure
pytest -x
```

## Performance Testing

Use pytest-benchmark for performance tests:

```python
def test_performance(benchmark):
    """Test performance of operation."""
    result = benchmark(my_slow_function, arg1, arg2)
    assert result is not None
```

## Testing Checklist

Before submitting a PR please check the following:

- [ ] All tests pass
- [ ] Coverage maintained or improved
- [ ] New features have tests
- [ ] Obvious edge cases covered
- [ ] Tests are documented
