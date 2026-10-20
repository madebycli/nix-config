# Temporary workaround for the load-sensitive pyrate-limiter 4.5.0 tests.
# Remove after upstream fixes https://github.com/vutran1710/PyrateLimiter/issues/247.
# Keep the package code, remaining test suite and import check unchanged.
_final: prev:
{
  pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
    (_pythonFinal: pythonPrev:
      prev.lib.optionalAttrs (pythonPrev.pyrate-limiter.version == "4.5.0") {
        pyrate-limiter = pythonPrev.pyrate-limiter.overridePythonAttrs (old: {
          disabledTests = (old.disabledTests or [ ]) ++ [
            # Tight wall-clock bounds and leak deadlines fail under load.
            "test_limiter_async_factory_get"
            "test_factory_leak"
          ];
          disabledTestPaths = (old.disabledTestPaths or [ ]) ++ [
            # Async Redis fixture timed out during the reported clean install.
            "tests/test_bucket_factory.py::test_factory_01[create_async_redis_bucket]"
          ];
        });
      })
  ];
}
