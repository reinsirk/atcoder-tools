class ExpandConfig:

    def __init__(self, include_dirs=None, expanded_filename=None):
        if include_dirs is not None and (
                not isinstance(include_dirs, list)
                or not all(isinstance(path, str) for path in include_dirs)):
            raise ValueError('expand.include_dirs must be a list of paths')
        if expanded_filename is not None and (
                not isinstance(expanded_filename, str) or not expanded_filename.strip()):
            raise ValueError(
                'expand.expanded_filename must be a non-empty path string')
        self.include_dirs = include_dirs or []
        self.expanded_filename = expanded_filename
