import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.optimization_metadata import metadata_from_path


class MetadataTest(unittest.TestCase):
    def test_known_chart_labels_and_unknown_columns(self):
        from app.analysis import chart_column_label
        self.assertEqual(chart_column_label('Q_m3_h'),'气体流量 Q (m³/h)')
        self.assertEqual(chart_column_label('unrecognized_column'),'unrecognized_column')

    def test_marked_height_and_parameters(self):
        result=metadata_from_path(Path('Q=1.8,1WT%,10%PL,H2_files')/'0001.tif')
        self.assertEqual(result['values'],{'current_q':1.8,'salinity_wt_pct':1.,'PL_fraction':.1,'height_m':.8})

    def test_user_confirmed_h3_and_pl(self):
        result=metadata_from_path(Path('盐水不同气泡1')/'Q=1.8,2.5WT%,15%_files'/'0001.tif')
        self.assertEqual(result['values']['height_m'],1.2)
        self.assertEqual(result['values']['PL_fraction'],.15)

    def test_ambiguous_or_missing_values_are_not_invented(self):
        result=metadata_from_path(Path('盐水不同气泡1')/'Q=1.8,1WT%,10%PL,H1,H2'/'a.tif')
        self.assertNotIn('height_m',result['values'])
        self.assertEqual(metadata_from_path('plain/image.png')['values'],{})

    def test_original_path_api(self):
        from fastapi.testclient import TestClient
        from app.main import app,sessions
        from app.storage import Session
        with TemporaryDirectory() as tmp:
            folder=Path(tmp)/'Q=1.8,1WT%,10%PL,H1_files';folder.mkdir()
            image=folder/'a.png';image.write_bytes(b'fixture')
            session=Session();sessions[session.id]=session
            try:
                with TestClient(app) as client:
                    response=client.post(f'/api/sessions/{session.id}/optimization-image',json={'path':str(image)})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.json()['optimization_metadata']['values']['height_m'],.2)
            finally:sessions.pop(session.id,None)


if __name__=='__main__':unittest.main()
