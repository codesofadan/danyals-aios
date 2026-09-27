"""Module 05 - Web 2.0 & Social Publishing (``docs/aios-v2/modules/M05-web2-and-social.md``).

The v1 implementation of this module is spread across ``app/services/web2_*`` and
``integrations/web2_*``; this package is where its v2 shape accretes, starting with the
``campaign_content`` GRAPH. Nothing here replaces the running pipeline - the graph calls
the same pure stage functions, so the two paths produce identical output and the graph
adds only what a straight-line function cannot have: a checkpoint after every node.
"""
