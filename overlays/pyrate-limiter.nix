# Temporary workaround for the load-sensitive pyrate-limiter 4.5.0 tests.
# Remove after upstream fixes https://github.com/vutran1710/PyrateLimiter/issues/247.
# Keep the package code, remaining test suite and import check unchanged.
_final: prev:
{
  pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
    (_pythonFinal: pythonPrev: {
      pyrate-limiter = pythonPrev.pyrate-limiter.overridePythonAttrs (old:
        # Check the version inside the override, after the Python scope exists.
        prev.lib.optionalAttrs (old.version == "4.5.0") {
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
