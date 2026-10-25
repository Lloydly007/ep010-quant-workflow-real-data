# 热点剖析（6 份配置，20140101~20221231）

- 面板加载（不计入）：0.2s，shape=(333944, 43)
- 回测墙钟：5.3s，单份均 0.88s
- 成功：6/6

## 按源文件聚合 tottime（自身时间，不含子调用）

| 占比 | 秒/份 | 文件:行 |
|---|---|---|
| 48.7% | 0.43 | `.\engine\backtest.py` |
| 23.9% | 0.21 | `~` |
| 7.4% | 0.07 | `.venv\Lib\site-packages\numpy\_core\fromnumeric.py` |
| 4.8% | 0.04 | `.\engine\ch14.py` |
| 4.4% | 0.04 | `.venv\Lib\site-packages\pandas\core\arrays\arrow\array.py` |
| 1.2% | 0.01 | `.venv\Lib\site-packages\pandas\core\internals\construction.py` |
| 1.0% | 0.01 | `.\engine\panel_store.py` |
| 0.7% | 0.01 | `.venv\Lib\site-packages\numpy\_core\_ufunc_config.py` |
| 0.5% | 0.00 | `.venv\Lib\site-packages\numpy\_core\numeric.py` |
| 0.5% | 0.00 | `.venv\Lib\site-packages\pandas\io\formats\csvs.py` |
| 0.5% | 0.00 | `.venv\Lib\site-packages\pandas\core\arrays\string_arrow.py` |
| 0.5% | 0.00 | `.venv\Lib\site-packages\numpy\_core\_methods.py` |
| 0.4% | 0.00 | `.venv\Lib\site-packages\pyarrow\parquet\core.py` |
| 0.4% | 0.00 | `.\engine\operators.py` |

## 函数级 Top 20（cumtime）

```
         6691168 function calls (6685857 primitive calls) in 5.299 seconds

   Ordered by: cumulative time
   List reduced from 1436 to 20 due to restriction <20>

   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
        1    0.005    0.005    5.299    5.299 <v2 实验目录>\engine\funnel.py:671(run)
        6    0.000    0.000    5.294    0.882 <v2 实验目录>\engine\funnel.py:569(_run_one)
        6    0.001    0.000    5.294    0.882 <v2 实验目录>\engine\backtest.py:1623(run_backtest)
        6    0.000    0.000    3.364    0.561 <v2 实验目录>\engine\backtest.py:1257(run)
        6    0.600    0.100    3.364    0.561 <v2 实验目录>\engine\backtest.py:953(_run_rule)
        6    0.005    0.001    1.472    0.245 <v2 实验目录>\engine\backtest.py:1445(_attach_ch14)
        6    0.160    0.027    1.467    0.244 <v2 实验目录>\engine\backtest.py:1303(_ch14_compute)
   403886    0.162    0.000    1.026    0.000 .venv\Lib\site-packages\numpy\_core\fromnumeric.py:1459(searchsorted)
406296/406284    0.189    0.000    0.895    0.000 .venv\Lib\site-packages\numpy\_core\fromnumeric.py:48(_wrapfunc)
        6    0.208    0.035    0.767    0.128 <v2 实验目录>\engine\ch14.py:251(hold_value_from_intervals)
   155404    0.240    0.000    0.673    0.000 <v2 实验目录>\engine\backtest.py:703(row_of)
   201822    0.293    0.000    0.668    0.000 <v2 实验目录>\engine\backtest.py:1287(_ch14_nav_at)
   403886    0.630    0.000    0.630    0.000 {method 'searchsorted' of 'numpy.ndarray' objects}
   108178    0.029    0.000    0.526    0.000 <v2 实验目录>\engine\backtest.py:1333(<lambda>)
    14088    0.074    0.000    0.522    0.000 <v2 实验目录>\engine\backtest.py:846(_mark_nav)
    14082    0.255    0.000    0.505    0.000 <v2 实验目录>\engine\backtest.py:787(_cross_arrays)
    14088    0.068    0.000    0.486    0.000 <v2 实验目录>\engine\backtest.py:837(_nav_est)
    96577    0.143    0.000    0.416    0.000 <v2 实验目录>\engine\backtest.py:719(_last_row_before)
   200437    0.064    0.000    0.412    0.000 <v2 实验目录>\engine\backtest.py:1044(<genexpr>)
   209435    0.109    0.000    0.356    0.000 <v2 实验目录>\engine\backtest.py:768(_val)



```