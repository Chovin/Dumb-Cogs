"""
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this file,
You can obtain one at https://mozilla.org/MPL/2.0/.

https://github.com/Rapptz/RoboDanny/blob/rewrite/cogs/admin.py#L97-L104
"""

def cleanup_code(content):
    """Automatically removes code blocks from the code."""
    # remove ```py\n```
    if content.startswith(('```','`​`​`')) and content.endswith(('```','`​`​`')):
        return '\n'.join(content.split('\n')[1:-1])

    # remove `foo`
    for p in ['`', '']:
        if content.startswith(p):
            if p == '`':
                return content.strip('` \n')
            content = content[len(p):]
            return content.strip(' \n')