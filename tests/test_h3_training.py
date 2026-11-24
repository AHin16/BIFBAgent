import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from optimization_data.h3 import train


class H3TrainingTest(unittest.TestCase):
    def test_complete_data_and_holdout_grouping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / 'data.sqlite3'
            selected = []
            with closing(sqlite3.connect(db)) as conn:
                conn.execute('create table images (image_id text, metadata text, status text, result text)')
                i = 0
                for source in ('盐水不同气泡1', '盐水不同照片2'):
                    for q, salinity, pl in ((1.5,1,.1),(1.8,1,.1),(2.,1,.1),(2.3,1,.1),(1.8,.5,.1),(1.8,1.5,.1),(1.8,1,.05),(1.8,1,.15)):
                        i += 1
                        meta = {'image_id':str(i), 'image_path':f'{source}/{i}', 'source_root':source,
                                'sequence_id':str(i), 'Q_m3_h':str(q), 'Ug_m_s':str(q*.00325),
                                'salinity_wt_pct':str(salinity), 'PL_fraction':str(pl),
                                'height_id':'H3', 'height_m':'1.2', 'height_source':'user_confirmation_2026-11-15'}
                        result = {'clean':{'d50_px':100+q+salinity+pl,'count':8},'all':{'d50_px':110},
                                  'image_count':10,'edge_or_unknown':2}
                        selected.append(meta)
                        conn.execute('insert into images values (?,?,?,?)',(str(i),json.dumps(meta),'success',json.dumps(result)))
                conn.commit()
            with patch.object(train, 'selected_images', return_value=selected), patch.object(train, 'incomplete_images', return_value=[]), patch.object(train, 'DB', db), patch.object(train, 'OUTPUT', root/'out'):
                train.main()
            result = json.loads((root/'out/model.json').read_text(encoding='utf-8'))
            folds = pd.read_csv(root/'out/leave_one_condition_out.csv')
            self.assertEqual(result['metrics']['image_count'], 16)
            self.assertEqual(result['metrics']['condition_combinations'], 8)
            self.assertEqual(len(folds), 16)
            self.assertLess(result['metrics']['mae_px'], 1e-8)


if __name__ == '__main__':
    unittest.main()
