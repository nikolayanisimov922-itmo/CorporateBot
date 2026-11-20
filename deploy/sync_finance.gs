/**
 * Зеркало финансовой таблицы «ДДС ОАЭ 2026» для бота.
 *
 * Где живёт: в таблице «Финансы - для бота» (Мой диск Николая) →
 * Расширения → Apps Script. Раз в 15 минут копирует ВСЕ листы основной
 * таблицы (только значения, с форматами чисел/дат), новые листы добавляет,
 * удалённые — удаляет. Лист «_обновлено» — время последней копии.
 *
 * Установка: вставить код → выбрать функцию setupTrigger → «Выполнить» →
 * разрешить доступ. Повторно запускать не нужно.
 */

// ID основной таблицы — часть ссылки между /d/ и /edit
const SOURCE_ID = '1GeLwhjyUfP_q_WjNUfVJ5AAnVPEkEbj6NDR9H3vfwKw';
const STAMP_SHEET = '_обновлено';

function syncFinance() {
  const src = SpreadsheetApp.openById(SOURCE_ID);
  const dst = SpreadsheetApp.getActiveSpreadsheet();
  const names = [];

  src.getSheets().forEach(function (s) {
    const name = s.getName();
    names.push(name);
    let t = dst.getSheetByName(name);
    if (!t) t = dst.insertSheet(name, dst.getSheets().length);

    const rows = s.getLastRow();
    const cols = s.getLastColumn();
    if (rows > 0 && cols > 0) {
      if (t.getMaxRows() < rows) t.insertRowsAfter(t.getMaxRows(), rows - t.getMaxRows());
      if (t.getMaxColumns() < cols) t.insertColumnsAfter(t.getMaxColumns(), cols - t.getMaxColumns());
      const range = s.getRange(1, 1, rows, cols);
      const values = range.getValues();
      const srcFormats = range.getNumberFormats();
      // Текст пишем как текст («12-03» не должно превратиться в дату),
      // числа и даты — с форматом из основной таблицы.
      const formats = values.map(function (row, i) {
        return row.map(function (v, j) {
          return typeof v === 'string' ? '@' : srcFormats[i][j];
        });
      });
      const out = t.getRange(1, 1, rows, cols);
      out.setNumberFormats(formats);
      out.setValues(values);
    }
    // Стираем хвост, если в основной таблице стало меньше строк/столбцов.
    const lastR = t.getLastRow();
    const lastC = t.getLastColumn();
    if (lastR > rows) t.getRange(rows + 1, 1, lastR - rows, Math.max(lastC, 1)).clearContent();
    if (lastC > cols && rows > 0) t.getRange(1, cols + 1, rows, lastC - cols).clearContent();
  });

  const stamp = dst.getSheetByName(STAMP_SHEET) || dst.insertSheet(STAMP_SHEET, dst.getSheets().length);
  stamp.getRange(1, 1, 1, 2).setValues([['Обновлено', new Date()]]);

  // Листы, которых больше нет в основной таблице (и пустой «Лист1»), удаляем.
  dst.getSheets().forEach(function (t) {
    const n = t.getName();
    if (n !== STAMP_SHEET && names.indexOf(n) === -1) dst.deleteSheet(t);
  });
}

/** Запустить один раз: ставит обновление каждые 15 минут и сразу копирует. */
function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncFinance') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('syncFinance').timeBased().everyMinutes(15).create();
  syncFinance();
}
