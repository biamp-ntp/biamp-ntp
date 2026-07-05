"""Instance-ID discovery for a running Biamp design.

Instance IDs change on every recompile+push, so numbers taken from a .nex file
go stale. Sweep a GET across candidate instance IDs; only a real block of the
matching type answers with a value instead of an -ERR:XACTION ERROR.
"""

__all__ = ["scan"]


def scan(client, attr, *idx, rng=range(1, 200)):
    """Yield ``(instance_id, value)`` for each instance that answers ``attr``.

    ``idx`` defaults to ``(1,)`` (the first channel). Example::

        from biamp_ntp import BiampNTP, scan, protocol as p
        with BiampNTP("192.168.1.199") as dsp:
            for inst, val in scan(dsp, p.OUTPUT_LEVEL_PM):
                print(inst, val)

    Widen ``rng`` if nothing turns up -- large designs can push instance IDs
    well past the default upper bound.
    """
    if not idx:
        idx = (1,)
    for inst in rng:
        r = client.query(attr, inst, *idx)
        if r and not r.startswith("-ERR"):
            yield inst, r
