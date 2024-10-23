from datetime import datetime,timedelta
from typing import Any

class ExpiringDict(dict):
    def __init__(self, *args, **kwargs):
        self.max_age = kwargs.pop('max_age', 0)
        if self.max_age <= 0:
            raise ValueError('max_age must be given as > 0')
        self.delta = timedelta(seconds=self.max_age)
        self.update(*args, **kwargs)

    def __setitem__(self, key: Any, value: Any):
        super().__setitem__(key, (value, datetime.now()))
    
    def __getitem__(self, key: Any) -> Any:
        ret = super().__getitem__(key)
        if ret[1] + self.delta < datetime.now():
            del self[key]
            raise KeyError
        return ret[0]
    
    def update(self, *args, **kwargs):
        for k, v in dict(*args, **kwargs).items():
            self[k] = v
        
    def pop(self, key, *args, **kwargs):
        try:
            ret = self[key]
        except KeyError as e:
            if 'default' in kwargs:
                return kwargs['default']
            if args:
                return args[0]
            raise e
        
        del self[key]

        return ret