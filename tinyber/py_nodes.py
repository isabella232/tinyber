# -*- Mode: Python -*-

from tinyber import nodes
from tinyber.writer import Writer
import sys

def psafe (s):
    return s.replace ('-', '_')

class c_base_type (nodes.c_base_type):

    def emit (self, out):
        pass

    def emit_decode (self, out):
        type_name, min_size, max_size = self.attrs
        if type_name == 'INTEGER':
            out.writelines ('v = src.next_INTEGER (%s,%s)' % (min_size, max_size),)
        elif type_name == 'OCTET STRING':
            out.writelines ('v = src.next_OCTET_STRING (%s,%s)' % (min_size, max_size),)
        elif type_name == 'BOOLEAN':
            out.writelines ('v = src.next_BOOLEAN()')
        else:
            import pdb; pdb.set_trace()

    def emit_encode (self, out, val):
        type_name, min_size, max_size = self.attrs
        if type_name == 'INTEGER':
            out.writelines ('dst.emit_INTEGER (%s)' % (val,))
        elif type_name == 'OCTET STRING':
            out.writelines ('dst.emit_OCTET_STRING (%s)' % (val,))
        elif type_name == 'BOOLEAN':
            out.writelines ('dst.emit_BOOLEAN (%s)' % (val,))
        else:
            import pdb; pdb.set_trace()

class c_sequence (nodes.c_sequence):

    parent_class = 'SEQUENCE'

    def emit (self, out):
        name, slots = self.attrs
        types = self.subs
        out.writelines ('__slots__ = (%s)' % (', '.join ("'%s'" % x for x in slots)))

    def emit_decode (self, out):
        name, slots = self.attrs
        types = self.subs
        out.writelines ('src = src.next (TAG.SEQUENCE)')
        for i in range (len (slots)):
            slot_name = slots[i]
            slot_type = types[i]
            slot_type.emit_decode (out)
            out.writelines ('self.%s = v' % (slot_name,))

    def emit_encode (self, out, val):
        name, slots = self.attrs
        types = self.subs
        out.writelines ('with dst.TLV (TAG.SEQUENCE):')
        with out.indent():
            for i in reversed (range (len (types))):
                types[i].emit_encode (out, 'self.%s' % (slots[i],))

class c_sequence_of (nodes.c_sequence_of):

    def emit (self, out):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs

    def emit_decode (self, out):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs
        out.writelines (
            'src, save = src.next (TAG.SEQUENCE), src',
            'a = []',
            'while not src.done():'
            )
        with out.indent():
            seq_type.emit_decode (out)
            out.writelines ('a.append (v)')
        out.writelines ("# check constraints")
        out.writelines ('v, src = a, save')

    def emit_encode (self, out, val):
        min_size, max_size, = self.attrs
        [seq_type] = self.subs
        out.writelines ('with dst.TLV (TAG.SEQUENCE):')
        with out.indent():
            out.writelines ('for v in reversed (%s):' % (val,))
            with out.indent():
                seq_type.emit_encode (out, 'v')

class c_choice (nodes.c_choice):

    parent_class = 'CHOICE'
    nodecoder = True
    noencoder = True

    def emit (self, out):
        name, slots, tags = self.attrs
        types = self.subs
        pairs = []
        for i in range (len (slots)):
            pairs.append ((types[i].name(), tags[i]))
        out.writelines ('tags_f = {%s}' % (', '.join (('%s:%s' % (x[0], x[1]) for x in pairs))))
        out.writelines ('tags_r = {%s}' % (', '.join (('%s:%s' % (x[1], x[0]) for x in pairs))))
        
class c_enumerated (nodes.c_enumerated):

    def emit (self, out):
        alts, = self.attrs
        pairs = []
        for name, val in alts:
            pairs.append ((name, val))
        out.writelines ('tags_f = {%s}' % (', '.join (("'%s':%s" % (x[0], x[1]) for x in pairs))))
        out.writelines ('tags_r = {%s}' % (', '.join (("%s:'%s'" % (x[1], x[0]) for x in pairs))))

    parent_class = 'ENUMERATED'
    nodecoder = True
    noencoder = True

class c_defined (nodes.c_defined):

    def emit (self, out):
        name, max_size = self.attrs

    def emit_decode (self, out):
        type_name, max_size = self.attrs
        out.writelines (
            'v = %s()' % (type_name,),
            'v._decode(src)',
            )

    def emit_encode (self, out, val):
        type_name, max_size = self.attrs
        out.writelines ('%s._encode (dst)' % (val,))



class PythonBackend:

    def __init__ (self, walker, module_name, base_path):
        self.walker = walker
        self.module_name = module_name
        self.base_path = base_path

    def gen_decoder (self, type_name, type_decl, node):
        # generate a decoder for a type assignment.
        self.out.writelines ('def _decode (self, src):')
        with self.out.indent():
            node.emit_decode (self.out)
            # this line is unecessary (but harmless) on normal defined sequence types
            self.out.writelines ('self.value = v')
        
    def gen_encoder (self, type_name, type_decl, node):
        # generate an encoder for a type assignment
        self.out.writelines ('def _encode (self, dst):')
        with self.out.indent():
            node.emit_encode (self.out, 'None')

    def gen_codec_funs (self, type_name, type_decl, node):
        if not hasattr (node, 'nodecoder'):
            self.gen_decoder (type_name, type_decl, node)
        if not hasattr (node, 'noencoder'):
            self.gen_encoder (type_name, type_decl, node)

    def generate_code (self):
        self.out = Writer (open (self.base_path + '_ber.py', 'wb'), indent_size=4)
        self.out.writelines (
            '# -*- Mode: Python -*-',
            '# generated by %r' % sys.argv,
            '# *** do not edit ***',
            '',
            'from tinyber.codec import *',
        )
        self.tag_assignments = self.walker.tag_assignments
        # generate typedefs and prototypes.
        for (type_name, node, type_decl) in self.walker.defined_types:
            if hasattr (node, 'parent_class'):
                parent_class = node.parent_class
            else:
                parent_class = 'ASN1'
            self.out.writelines ('', 'class %s (%s):' % (type_name, parent_class))
            with self.out.indent():
                self.out.writelines (
                    'max_size = %d' % (node.max_size())
                )
                node.emit (self.out)
                self.gen_codec_funs (type_name, type_decl, node)
        self.out.close()

        