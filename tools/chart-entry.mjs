// Tree-shaken Chart.js entry — 只 import 本站用到的元件(line chart + fill + log/linear/category 軸 + legend/tooltip)。
// esbuild bundle+minify → site/vendor/chart.min.js,暴露 window.Chart 給 index.html 內聯腳本用。
// 換 Chart.js 版本或用到新圖型時:改這裡的 import → npm run build:vendor → commit 產物。
import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  LogarithmicScale,
  CategoryScale,
  Filler,
  Legend,
  Tooltip,
} from "chart.js";

Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  LogarithmicScale,
  CategoryScale,
  Filler,
  Legend,
  Tooltip,
);

window.Chart = Chart;
