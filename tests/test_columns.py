import random
import sys
from array import array
from pickle import loads, dumps
from typing import List

from whoosh import columns
# from whoosh import fields
# from whoosh import query
# from whoosh.filedb.filestore import RamStorage
from whoosh.util.testing import TempIndex, TempStorage


def test_pickleability():
    # Column types and initial arguments
    coltypes = {
        columns.VarBytesColumn: (),
        columns.FixedBytesColumn: (5,),
        columns.RefBytesColumn: (),
        columns.NumericColumn: ("i",),
        columns.BitColumn: (),
        columns.PickleColumn: (columns.VarBytesColumn(),),
        columns.CompressedBytesColumn: (),
        columns.BlockCompressedColumn: (),
        # columns.StructColumn: ("i", 0),
    }

    for coltype, args in coltypes.items():
        try:
            inst = coltype(*args)
        except TypeError as e:
            raise TypeError("Error instantiating %r: %s" % (coltype, e))

        p = dumps(inst, -1)
        _ = loads(p)


def _rt(c: columns.Column, values: List, default):
    with TempStorage() as st:
        # Continuous
        with st.create_file("test1") as f:
            f.write(b"hello")
            w = c.writer(f)
            for docnum, v in enumerate(values):
                w.add(docnum, v)
            w.finish(len(values))
            length = f.tell() - 5

        with st.map_file("test1") as m:
            r = c.reader(m, 5, length, len(values), True)
            assert list(r) == values
            for x in range(len(values)):
                assert r[x] == values[x]
            r.close()

        # Sparse
        doccount = len(values) * 7 + 15
        target = [default] * doccount

        with st.create_file("test2") as f:
            f.write(b"hello")
            w = c.writer(f)
            for docnum, v in zip(range(10, doccount, 7), values):
                target[docnum] = v
                w.add(docnum, v)
            w.finish(doccount)
            length = f.tell() - 5

        with st.map_file("test2") as m:
            r = c.reader(m, 5, length, doccount, True)
            assert list(r) == target
            for x in range(doccount):
                assert r[x] == target[x]
            r.close()


def test_roundtrip_var():
    _rt(columns.VarBytesColumn(), [b"a", b"ccc", b"bbb", b"e", b"dd"], b"")


def test_roundtrip_fixed():
    _rt(columns.FixedBytesColumn(5),
        [b"aaaaa", b"eeeee", b"ccccc", b"bbbbb", b"eeeee"],
        b"\x00" * 5)


def test_roundtrip_ref():
    _rt(columns.RefBytesColumn(),
        [b"a", b"ccc", b"bb", b"ccc", b"a", b"bb"], b"")


def test_roundtrip_fixedref():
    _rt(columns.RefBytesColumn(3),
        [b"aaa", b"bbb", b"ccc", b"aaa", b"bbb", b"ccc"],
        b"\x00" * 3)


# def test_roundtrip_struct():
#     _rt(columns.StructColumn("ifH", (0, 0.0, 0)),
#         [(100, 1.5, 15000), (-100, -5.0, 0), (5820, 6.5, 462),
#          (-57829, -1.5, 6), (0, 0, 0)],
#         (0, 0.0, 0))


def test_roundtrip_nums():
    numcol = columns.NumericColumn
    _rt(numcol("b"), [10, -20, 30, -25, 15], 0)
    _rt(numcol("B"), [10, 20, 30, 25, 15], 0)
    _rt(numcol("h"), [1000, -2000, 3000, -15000, 32000], 0)
    _rt(numcol("H"), [1000, 2000, 3000, 15000, 50000], 0)
    _rt(numcol("i"), [2 ** 16, -(2 ** 20), 2 ** 24, -(2 ** 28), 2 ** 30], 0)
    _rt(numcol("I"), [2 ** 16, 2 ** 20, 2 ** 24, 2 ** 28, 2 ** 31 & 0xFFFFFFFF], 0)
    _rt(numcol("q"), [10, -20, 30, -25, 15], 0)
    _rt(numcol("Q"), [2 ** 35, 2 ** 40, 2 ** 48, 2 ** 52, 2 ** 63], 0)
    _rt(numcol("f"), [1.5, -2.5, 3.5, -4.5, 1.25], 0)
    _rt(numcol("d"), [1.5, -2.5, 3.5, -4.5, 1.25], 0)


def _test_roundtrip_bits():
    c = columns.BitColumn()
    _rt(c, [bool(random.randint(0, 1)) for _ in range(70)], False)
    _rt(c, [bool(random.randint(0, 1)) for _ in range(900)], False)


def _test_roundtrip_pickles():
    c = columns.PickleColumn(columns.VarBytesColumn())
    _rt(c, [None, True, False, 100, -7, "hello"], None)


def test_non_native():
    nums = array("i", [-1, 10, -20, 300, -400, 5000])
    swapped = array("i", nums)
    swapped.byteswap()
    c = columns.NumericColumn("i")

    with TempStorage() as st:
        with st.create_file("test.col") as f:
            w = c.writer(f)
            for i, x in enumerate(nums):
                w.add(i, x)
            w.finish(len(nums))
            length = f.tell()

        with st.map_file("test.col") as m:
            r = c.reader(m, 0, length, 1, native=False)
            for i, x in enumerate(swapped):
                assert r[i] == x
            r.close()


def test_compact_ints():
    times = 10000

    domain = []
    total = times * 5 + 5
    vals = [0] * total

    for i in range(times):
        docnum = i * 5
        v = i % 1000 - 500
        domain.append((docnum, v))
        vals[docnum] = v

    choices = list(range(len(domain)))
    random.shuffle(choices)

    compact = columns.CompactIntColumn()
    sparse = columns.SparseIntColumn()

    def _populate(cw):
        for docnum, v in domain:
            cw.add(docnum, v)
        cw.finish(total)

    def _check(col, m, length):
        cr = col.reader(m, 0, length, total, True)

        for i in choices:
            dn, v = domain[i]
            assert cr[dn] == v

        for dn, v in domain:
            assert cr[dn] == v

        for i, v in enumerate(vals):
            assert cr[i] == v

        assert list(cr) == vals
        cr.close()

    with TempStorage() as st:
        with st.create_file("compact") as f:
            _populate(compact.writer(f))
            compact_len = f.tell()

        with st.create_file("sparse") as f:
            _populate(sparse.writer(f))
            sparse_len = f.tell()

        with st.map_file("compact") as m:
            _check(compact, m, compact_len)

        with st.map_file("sparse") as m:
            _check(sparse, m, sparse_len)


# def test_multivalue():
#     schema = fields.Schema(s=fields.TEXT(sortable=True),
#                            n=fields.NUMERIC(sortable=True))
#     with TempIndex(schema) as ix:
#         with ix.writer() as w:
#             w.add_document(s=u"alfa foxtrot charlie".split(),
#                            n=[100, 200, 300])
#             w.add_document(s=u"juliet bravo india".split(), n=[10, 20, 30])
#
#         with ix.reader() as r:
#             scr = r.column_reader("s")
#             assert list(scr) == ["alfa", "juliet"]
#
#             ncr = r.column_reader("n")
#             assert list(ncr) == [100, 10]


# def test_column_field():
#     schema = fields.Schema(a=fields.TEXT(sortable=True),
#                            b=fields.COLUMN(columns.RefBytesColumn()))
#     with TempIndex(schema, "columnfield") as ix:
#         with ix.writer() as w:
#             w.add_document(a=u"alfa bravo", b=b"charlie delta")
#             w.add_document(a=u"bravo charlie", b=b"delta echo")
#             w.add_document(a=u"charlie delta", b=b"echo foxtrot")
#
#         with ix.reader() as r:
#             assert r.has_column("a")
#             assert r.has_column("b")
#
#             cra = r.column_reader("a")
#             assert cra[0] == u"alfa bravo"
#             assert type(cra[0]) == text_type
#
#             crb = r.column_reader("b")
#             assert crb[0] == b"charlie delta"
#             assert type(crb[0]) == bytes_type


# def test_column_query():
#     schema = fields.Schema(id=fields.STORED,
#                            a=fields.ID(sortable=True),
#                            b=fields.NUMERIC(sortable=True))
#     with TempIndex(schema, "columnquery") as ix:
#         with ix.writer() as w:
#             w.add_document(id=1, a=u"alfa", b=10)
#             w.add_document(id=2, a=u"bravo", b=20)
#             w.add_document(id=3, a=u"charlie", b=30)
#             w.add_document(id=4, a=u"delta", b=40)
#             w.add_document(id=5, a=u"echo", b=50)
#             w.add_document(id=6, a=u"foxtrot", b=60)
#
#         with ix.searcher() as s:
#             def check(q):
#                 return [s.stored_fields(docnum)["id"] for docnum in q.docs(s)]
#
#             q = query.ColumnQuery("a", u"bravo")
#             assert check(q) == [2]
#
#             q = query.ColumnQuery("b", 30)
#             assert check(q) == [3]
#
#             q = query.ColumnQuery("a", lambda v: v != u"delta")
#             assert check(q) == [1, 2, 3, 5, 6]
#
#             q = query.ColumnQuery("b", lambda v: v > 30)
#             assert check(q) == [4, 5, 6]


def test_ref_switch():
    import warnings

    col = columns.RefBytesColumn()

    def rw(size):
        with TempStorage() as st:
            with st.create_file("test") as f:
                cw = col.writer(f)
                for i in range(size):
                    cw.add(i, hex(i).encode("latin1"))
                cw.finish(size)
                length = f.tell()

            with st.map_file("test") as m:
                cr = col.reader(m, 0, length, size, True)
                for i in range(size):
                    v = cr[i]
                    # Column ignores additional unique values after 65535
                    if i <= 65535 - 1:
                        assert v == hex(i).encode("latin1")
                    else:
                        assert v == b''
                cr.close()

    rw(100)
    rw(255)
    rw(300)

    # Column warns on additional unique values after 65534
    with warnings.catch_warnings(record=True) as w:
        # Cause all warnings to always be triggered.
        warnings.simplefilter("always")
        rw(65537)

        assert len(w) == 2
        assert issubclass(w[-1].category, UserWarning)


def test_roaring_column():
    col = columns.RoaringBitColumn()

    def gen(seed, times=200000):
        random.seed(seed)
        # Each position has one of three values; 0 simulates a missing doc,
        # 1 is False, 2 is True
        return [random.randint(0, 2) for _ in range(times)]

    def rw(vals):
        with TempStorage() as st:
            with st.create_file("test") as f:
                cw = col.writer(f)
                for i, v in enumerate(vals):
                    if v:
                        cw.add(i, bool(v - 1))
                cw.finish(len(vals))
                length = f.tell()

            with st.map_file("test") as m:
                cr = col.reader(m, 0, length, len(vals), True)
                for i in range(len(vals)):
                    v = cr[i]
                    # print(i, vals[i], cr[i])
                    if v:
                        assert vals[i] == 2, i
                    else:
                        assert vals[i] != 2, i
                cr.close()

    rw(gen(568739))
    # rw(gen(100))


def test_sparse_readback():
    from datetime import datetime
    from whoosh.util import now
    from whoosh.util.times import datetime_to_long, long_to_datetime

    limit = 10000
    docnums = list(range(limit))
    random.shuffle(docnums)
    docnums = sorted(docnums[:limit // 3])

    col = columns.SparseIntColumn()
    with TempStorage() as st:
        with st.create_file("test") as f:
            cw = col.writer(f)
            for docnum in docnums:
                cw.add(docnum, datetime_to_long(datetime.utcnow()))
            cw.finish(limit)
            length = f.tell()

        with st.map_file("test") as m:
            t = now()
            cr = col.reader(m, 0, length, limit, True)
            for i, v in enumerate(cr):
                if v:
                    _ = long_to_datetime(v)
            # print(now() - t)


def test_compressedbytes_random_access():
    words = (b"alfa bravo charlie delta echo foxtrot golf hotel india juliet"
             ).split()
    values = []
    limit = 10000
    p = 0
    for i in range(limit):
        vs = []
        while len(vs) < 200:
            vs.append(words[p])
            p = (p + 1) % len(words)
        value = b" ".join(vs)
        values.append(value)

    order = list(range(limit))
    random.shuffle(order)

    col = columns.CompressedBytesColumn()
    with TempStorage() as st:
        output = st.create_file("test")
        cw = col.writer(output)
        for i, value in enumerate(values):
            cw.add(i, value)
        cw.finish(limit)
        length = output.tell()
        output.close()

        data = st.map_file("test")
        cr = col.reader(data, 0, length, limit, True)
        for i in order:
            assert cr[i] == values[i]


def test_block_compressed():
    words = "alfa bravo charlie delta echo foxtrot golf hotel india".split()

    def make_dict():
        size = random.randint(4, 6)
        keys = random.sample(words, size)
        d = {}
        for k in keys:
            length = random.randint(3, 7)
            d[k] = " ".join(random.choice(words) for _ in range(length))
        return d

    count = 5000
    docs = [make_dict() for _ in range(count)]

    col = columns.BlockCompressedColumn()
    with TempStorage() as st:
        with st.create_file("test") as f:
            cw = col.writer(f)
            for i, doc in enumerate(docs):
                cw.add(i, doc)
            cw.finish(count)
            length = f.tell()
            # print(length)

        with st.map_file("test") as m:
            # Random access
            cr = col.reader(m, 0, length, count, True)
            order = list(range(count))
            random.shuffle(order)
            for docnum in order:
                stored = cr[docnum]
                # print("docnum=", docnum, "stored=", stored)
                assert stored == docs[docnum]
            cr.close()

            # Iterator
            cr = col.reader(m, 0, length, count, True)
            for i, v in enumerate(cr):
                assert v == docs[i]
            cr.close()


def test_sparse_block_compressed():
    words = ("alfa bravo charlie delta echo foxtrot golf hotel india juliet"
             "kilo lima mike november oskar papa quebec romeo sierra tango"
             "uniform victor whiskey xray yankee zulu"
             ).split()

    ds = []
    for w1 in words:
        for w2 in words:
            for w3 in words[:5]:
                ds.append({w1: " ".join((w2, w3))})

    count = 3000
    docnum = 0
    docs = []
    for d in ds:
        docnum += random.randint(5, 10)
        docs.append((docnum, d))
    ddict = dict(docs)
    maxdoc = docnum

    col = columns.BlockCompressedColumn()
    with TempStorage() as st:
        with st.create_file("test") as f:
            cw = col.writer(f)
            for docnum, doc in docs:
                cw.add(docnum, doc)
            cw.finish(count)
            length = f.tell()

        with st.map_file("test") as m:
            cr = col.reader(m, 0, length, count, True)

            for i in range(maxdoc + 10):
                x = cr[i]
                y = ddict.get(i)
                assert x == y

            cr = col.reader(m, 0, length, count, True)
            vs = list(cr)
            cr.close()
            assert len(vs) == maxdoc + 1
            assert vs == [ddict.get(i) for i in range(maxdoc + 1)]


def test_annotation_column():
    domain = [
        (0, [("foo", 0, 2), ("bar", 10, 20), ("corp", 0, 1)]),
        (2, [("person", 15, 20)]),
        (7, [("person", 30, 35), ("corp", 60, 80)]),
        (12, [("foo", 6, 7), ("bar", 8, 12), ("person", 15, 56)]),
        (18, [("boof", 0, 8)]),
    ]

    col = columns.AnnotationColumn()
    with TempStorage() as st:
        with st.create_file("test") as f:
            cw = col.writer(f)
            for docnum, annos in domain:
                cw.add(docnum, annos)
            cw.finish(20)
            length = f.tell()

        with st.map_file("test") as m:
            cr = col.reader(m, 0, length, 20, True)
            assert cr.names() == ("foo", "bar", "corp", "person", "boof")
            assert domain[4][1] == list(cr[18])
            assert domain[0][1] == list(cr[0])
            assert domain[2][1] == list(cr[7])
            assert domain[1][1] == list(cr[2])
            assert domain[3][1] == list(cr[12])
            assert [] == list(cr[5])
            assert [] == list(cr[25])


def test_path_column():
    paths = """
    /foo/
    /sphinx/__main__.py
    /sphinx/project.py
    /karma.conf.js
    /EXAMPLES
    /tox.ini
    /doc/man/index.rst
    /doc/man/sphinx-autogen.rst
    /doc/man/sphinx-build.rst
    /doc/man/sphinx-quickstart.rst
    /doc/man/sphinx-apidoc.rst
    /doc/extdev/projectapi.rst
    /doc/extdev/index.rst
    /doc/extdev/parserapi.rst
    /doc/extdev/markupapi.rst
    /doc/extdev/appapi.rst
    /doc/extdev/envapi.rst
    /doc/extdev/domainapi.rst
    /doc/extdev/i18n.rst
    /doc/extdev/builderapi.rst
    /doc/extdev/logging.rst
    /doc/extdev/nodes.rst
    /doc/extdev/deprecated.rst
    /doc/extdev/utils.rst
    /doc/extdev/collectorapi.rst
    /doc/templating.rst
    /doc/_themes/sphinx13/layout.html
    /doc/_themes/sphinx13/theme.conf
    /doc/_themes/sphinx13/static/headerbg.png
    /doc/_themes/sphinx13/static/relbg.png
    /doc/_themes/sphinx13/static/bodybg.png
    /doc/_themes/sphinx13/static/sphinxheader.png
    /doc/_themes/sphinx13/static/sphinx13.css
    /doc/_themes/sphinx13/static/footerbg.png
    /doc/_themes/sphinx13/static/listitem.png
    /doc/contents.rst
    /doc/intro.rst
    /doc/development/tutorials/index.rst
    /doc/development/tutorials/todo.rst
    /doc/development/tutorials/helloworld.rst
    /doc/development/tutorials/examples/helloworld.py
    /doc/development/tutorials/examples/recipe.py
    /doc/development/tutorials/examples/README.rst
    /doc/development/tutorials/examples/todo.py
    /doc/development/tutorials/recipe.rst
    /doc/_templates/index.html
    /doc/_templates/indexsidebar.html
    /doc/Makefile
    /doc/conf.py
    /doc/examples.rst
    /doc/_static/translation.png
    /doc/_static/Makefile
    /doc/_static/conf.py.txt
    /doc/_static/pocoo.png
    /doc/_static/sphinx.png
    /doc/_static/translation.puml
    /doc/_static/bookcover.png
    /doc/_static/more.png
    /doc/_static/themes/bizstyle.png
    /doc/_static/themes/scrolls.png
    /doc/_static/themes/haiku.png
    /doc/_static/themes/alabaster.png
    /doc/_static/themes/classic.png
    /doc/_static/themes/fullsize/bizstyle.png
    /doc/_static/themes/fullsize/scrolls.png
    /doc/_static/themes/fullsize/haiku.png
    /doc/_static/themes/fullsize/alabaster.png
    /doc/_static/themes/fullsize/classic.png
    /doc/_static/themes/fullsize/traditional.png
    /doc/_static/themes/fullsize/nature.png
    /doc/_static/themes/fullsize/sphinxdoc.png
    /doc/_static/themes/fullsize/agogo.png
    /doc/_static/themes/fullsize/pyramid.png
    /doc/_static/themes/fullsize/sphinx_rtd_theme.png
    /doc/_static/themes/traditional.png
    /doc/_static/themes/nature.png
    /doc/_static/themes/sphinxdoc.png
    /doc/_static/themes/agogo.png
    /doc/_static/themes/pyramid.png
    /doc/_static/themes/sphinx_rtd_theme.png
    /doc/usage/advanced/intl.rst
    /doc/usage/advanced/setuptools.rst
    /doc/usage/advanced/websupport/index.rst
    /doc/usage/advanced/websupport/searchadapters.rst
    /doc/usage/advanced/websupport/quickstart.rst
    /doc/usage/advanced/websupport/storagebackends.rst
    /doc/usage/advanced/websupport/api.rst
    /doc/usage/markdown.rst
    /doc/usage/builders/index.rst
    /doc/usage/configuration.rst
    /doc/usage/extensions/intersphinx.rst
    /doc/usage/extensions/index.rst
    /doc/usage/extensions/extlinks.rst
    /doc/usage/extensions/example_google.rst
    /doc/usage/extensions/inheritance.rst
    /doc/usage/extensions/autosectionlabel.rst
    /doc/usage/extensions/napoleon.rst
    /doc/usage/extensions/viewcode.rst
    /doc/usage/extensions/todo.rst
    /doc/usage/extensions/githubpages.rst
    /doc/usage/extensions/autodoc.rst
    /doc/usage/extensions/example_numpy.rst
    /doc/usage/extensions/doctest.rst
    /doc/usage/extensions/ifconfig.rst
    /doc/usage/extensions/autosummary.rst
    /doc/usage/extensions/linkcode.rst
    /doc/usage/extensions/math.rst
    /doc/usage/extensions/example_google.py
    /doc/usage/extensions/graphviz.rst
    /doc/usage/extensions/imgconverter.rst
    /doc/usage/extensions/duration.rst
    /doc/usage/extensions/coverage.rst
    /doc/usage/extensions/example_numpy.py
    /doc/usage/theming.rst
    /doc/usage/quickstart.rst
    /doc/usage/installation.rst
    /doc/usage/restructuredtext/roles.rst
    /doc/usage/restructuredtext/index.rst
    /doc/usage/restructuredtext/domains.rst
    /doc/usage/restructuredtext/directives.rst
    /doc/usage/restructuredtext/field-lists.rst
    /doc/usage/restructuredtext/basics.rst
    """
    pathlist = [p.strip().encode("ascii") for p in paths.split("\n")
                if p.strip()] * 3
    doccount = len(pathlist)

    from whoosh.util import now
    with TempStorage() as st:
        col1 = columns.VarBytesColumn()
        col2 = columns.PathColumn()
        with st.create_file("test") as f:
            t = now()
            cw = col1.writer(f)
            for i, path in enumerate(pathlist):
                cw.add(i, path)
            cw.finish(doccount)
            length1 = f.tell()
            print(now() - t, length1)

            t = now()
            cw = col2.writer(f)
            for i, path in enumerate(pathlist):
                cw.add(i, path)
            cw.finish(doccount)
            length2 = f.tell() - length1
            print(now() - t, length2)
            print(length1 / length2, length2 / length1)

        docnums = list(range(doccount))
        random.shuffle(docnums)
        with st.map_file("test") as m:
            t = now()
            cr = col1.reader(m, 0, length1, doccount, native=True)
            for docnum in docnums:
                assert cr[docnum] == pathlist[docnum]
            cr.close()
            print(now() - t)

            t = now()
            cr = col2.reader(m, length1, length2, doccount, native=True)
            for docnum in docnums:
                assert cr[docnum] == pathlist[docnum]
            cr.close()
            print(now() - t)

    assert False



