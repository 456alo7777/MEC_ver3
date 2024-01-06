import os
from pathlib import Path

LINK_PROJECT = Path(os.path.abspath(__file__)) #lấy đường dẫn tuyệt đối của file hiện tại
LINK_PROJECT = LINK_PROJECT.parent.parent #định nghĩa link project- tức là link MEC3 nằm ở 2 bậc cao hơn từ __file__ hiện tại ()
print(LINK_PROJECT)
#print(LINK_PROJECT)
DATA_DIR = os.path.join(LINK_PROJECT, "data") #định nghĩa link data
RESULT_DIR = os.path.join(LINK_PROJECT, "result") #định nghĩa link result
DATA_TASK = os.path.join(LINK_PROJECT, "data_task") #định nghĩa link data_task
class Config:
    Pr = 46
    Pr2 = 24
    Wm = 10
    length_hidden_layer=4
    n_unit_in_layer=[16, 32, 32, 8]
    
