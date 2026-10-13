import copy
import json
from pathlib import Path

import pytest

from app.packs import load_pack
from app.store import Store
from builder.store import Catalog


def document():
    return dict(schema_version=1,title='Сетка',stages=[dict(id='g',type='grid',title='Темы',categories=['Космос','География'])],
                rounds=[dict(id='q',stage='g',type='question',category='Космос',text='Ближайшая к Солнцу планета?',answer='Меркурий')])


def load_document(tmp_path,doc):
    (tmp_path/'game.json').write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
    return load_pack(tmp_path)


@pytest.mark.parametrize('case',['missing','blank','unknown','not_string','no_categories','empty_name','duplicate','bad_list'])
def test_grid_categories_are_required_and_declared(tmp_path,case):
    doc=document()
    if case=='missing':doc['rounds'][0].pop('category')
    if case=='blank':doc['rounds'][0]['category']='  '
    if case=='unknown':doc['rounds'][0]['category']='Литература'
    if case=='not_string':doc['rounds'][0]['category']=10
    if case=='no_categories':doc['stages'][0]['categories']=[]
    if case=='empty_name':doc['stages'][0]['categories']=['Космос',' ']
    if case=='duplicate':doc['stages'][0]['categories']=['Космос','космос']
    if case=='bad_list':doc['stages'][0]['categories']='Космос'
    with pytest.raises(ValueError):load_document(tmp_path,doc)


def test_existing_grid_names_are_inferred_and_case_is_canonical(tmp_path):
    doc=document()
    doc['rounds'][0]['category']='  космос  '
    assert load_document(tmp_path,doc)['questions'][0]['category']=='Космос'
    doc['stages'][0].pop('categories')
    pack=load_document(tmp_path,doc)
    assert pack['stages'][0]['categories']==['космос']
    assert pack['questions'][0]['category']=='космос'


def test_invalid_category_draft_cannot_replace_published_game(tmp_path):
    catalog=Catalog(tmp_path/'builder',tmp_path/'games',Path(__file__).resolve().parents[1]/'games')
    snapshot=catalog.create('Сетка')
    snapshot=catalog.save(snapshot['id'],document(),snapshot['revision'])
    snapshot=catalog.publish(snapshot['id'],snapshot['revision'])
    manifest=catalog.games/snapshot['id']/'game.json'
    original=manifest.read_bytes()
    doc=copy.deepcopy(snapshot['document'])
    doc['rounds'][0].pop('category')
    snapshot=catalog.save(snapshot['id'],doc,snapshot['revision'])
    with pytest.raises(ValueError):catalog.publish(snapshot['id'],snapshot['revision'])
    assert manifest.read_bytes()==original
    assert 'category' not in catalog.open(snapshot['id'])['document']['rounds'][0]


def test_event_category_is_retained_alongside_question_category(tmp_path):
    doc=document()
    doc['stages'].insert(0,dict(id='b',type='blitz',title='Разминка'))
    doc['rounds'][:0]=[dict(id='warmup',stage='b',type='question',text='?',answer='Да',category='Космос'),
                       dict(id='event',stage='b',type='event',title='Бонус',category='Космос',effect=dict(type='random_buff',target='all_players',questions=1))]
    pack=load_document(tmp_path,doc)
    assert all(q['category']=='Космос' for q in pack['questions'])
    assert len([q for q in pack['questions'] if q['type']=='event'])==1
    assert len([q for q in pack['questions'] if q['type']=='question'])==2


def test_lobby_question_must_use_declared_grid_category(tmp_path):
    pack=load_document(tmp_path,document())
    store=Store(tmp_path/'game.sqlite3')
    host=dict(id='h',name='H')
    code=store.create(host,questions=pack['questions'],stages=pack['stages'])
    for category in ('','Unknown'):
        with pytest.raises(ValueError):store.add_question(code,host,dict(stage='g',text='?',answer='Да',value=100,category=category))
    store.add_question(code,host,dict(stage='g',text='?',answer='Да',value=100,category='география'))
    assert store.read(code)['pack'][-1]['category']=='География'
