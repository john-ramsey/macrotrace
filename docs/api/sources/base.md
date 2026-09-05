# Sources API Reference

Auto-generated documentation from source code docstrings. Note these are low level source details; for user-facing source guides see the [User Guide](../../sources/custom.md).

The base source class is a foundation for building specific data source integrations. It provides common functionality such as data fetching, updating, and state management.

## Base Classes

### SourceAdapter

::: macrotrace.sources.base.SourceAdapter

`MTTimeSeries` always resolves a lightweight source adapter. The adapter normalizes source identity and declares timestamp semantics without opening an API client or request cache. Its update-manager factory is called only when `update_prior_to_load=True`.

### UpdateState

::: macrotrace.sources.base.UpdateState

### APIClient

::: macrotrace.sources.base.APIClient
