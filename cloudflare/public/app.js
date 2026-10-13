const elements = {
  countdown: document.querySelector('#countdown'),
  days: document.querySelector('#days'),
  hours: document.querySelector('#hours'),
  minutes: document.querySelector('#minutes'),
  seconds: document.querySelector('#seconds'),
  statusLabel: document.querySelector('#status-label'),
  targetCaption: document.querySelector('#target-caption'),
  targetDate: document.querySelector('#target-date'),
  targetTime: document.querySelector('#target-time'),
  customDialog: document.querySelector('#custom-dialog'),
  customForm: document.querySelector('#custom-form'),
  customDate: document.querySelector('#custom-date'),
  customTime: document.querySelector('#custom-time'),
  customizeButton: document.querySelector('#customize-button'),
  closeDialog: document.querySelector('#close-dialog'),
  resetButton: document.querySelector('#reset-button'),
};

let targetTimestamp = getNextSundayTarget().getTime();
let isCustomTarget = false;

function pad(value) {
  return String(value).padStart(2, '0');
}

function getBeijingNow() {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  });
  const parts = Object.fromEntries(
    formatter.formatToParts(new Date())
      .filter(({ type }) => type !== 'literal')
      .map(({ type, value }) => [type, Number(value)]),
  );

  const weekdayNames = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const weekday = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    weekday: 'short',
  }).format(new Date());

  return { ...parts, dayOfWeek: weekdayNames[weekday] };
}

function getNextSundayTarget() {
  const now = getBeijingNow();
  const todayAtTarget = new Date(`${now.year}-${pad(now.month)}-${pad(now.day)}T18:35:00+08:00`);
  let daysUntilSunday = (7 - now.dayOfWeek) % 7;

  if (daysUntilSunday === 0 && Date.now() >= todayAtTarget.getTime()) {
    daysUntilSunday = 7;
  }

  const target = new Date(todayAtTarget.getTime() + daysUntilSunday * 24 * 60 * 60 * 1000);
  return target;
}

function formatTargetDate(timestamp) {
  const date = new Date(timestamp);
  const dateParts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: 'numeric',
    day: 'numeric',
  }).formatToParts(date);
  const month = dateParts.find(({ type }) => type === 'month')?.value ?? '--';
  const day = dateParts.find(({ type }) => type === 'day')?.value ?? '--';
  const weekDay = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', weekday: 'short' }).format(date);
  return `${month}月${day}日 ${weekDay}`;
}

function formatTargetTime(timestamp) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).format(new Date(timestamp));
}

function renderTargetDetails() {
  const targetDate = new Date(targetTimestamp);
  const targetTime = formatTargetTime(targetTimestamp);
  const weekDay = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', weekday: 'long' }).format(targetDate);

  elements.targetDate.textContent = formatTargetDate(targetTimestamp);
  elements.targetTime.textContent = targetTime;
  elements.targetCaption.textContent = isCustomTarget ? `目标：${formatTargetDate(targetTimestamp)} ${targetTime}` : `目标：周日下午 6:35`;
  elements.statusLabel.textContent = isCustomTarget ? `${weekDay}目标` : '距离下个周日';
}

function renderCountdown() {
  const distance = Math.max(0, targetTimestamp - Date.now());
  const totalSeconds = Math.floor(distance / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  elements.days.textContent = pad(days);
  elements.hours.textContent = pad(hours);
  elements.minutes.textContent = pad(minutes);
  elements.seconds.textContent = pad(seconds);
  elements.countdown.setAttribute('aria-label', `还剩 ${days} 天 ${hours} 小时 ${minutes} 分 ${seconds} 秒`);

  if (distance === 0) {
    elements.statusLabel.textContent = '目标时间到了';
  }
}

function setDefaultTarget() {
  targetTimestamp = getNextSundayTarget().getTime();
  isCustomTarget = false;
  renderTargetDetails();
  renderCountdown();
}

function getLocalDateInputValue(date) {
  const dateParts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date);
  const values = Object.fromEntries(dateParts.filter(({ type }) => type !== 'literal').map(({ type, value }) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function openCustomDialog() {
  const currentTarget = targetTimestamp > Date.now() ? new Date(targetTimestamp) : new Date();
  elements.customDate.value = getLocalDateInputValue(currentTarget);
  elements.customTime.value = formatTargetTime(currentTarget);
  elements.customDialog.showModal();
}

function closeCustomDialog() {
  elements.customDialog.close();
}

elements.customizeButton.addEventListener('click', openCustomDialog);
elements.closeDialog.addEventListener('click', closeCustomDialog);
elements.resetButton.addEventListener('click', setDefaultTarget);

elements.customDialog.addEventListener('click', (event) => {
  if (event.target === elements.customDialog) closeCustomDialog();
});

elements.customForm.addEventListener('submit', (event) => {
  event.preventDefault();
  const selectedDate = elements.customDate.value;
  const selectedTime = elements.customTime.value;
  const nextTarget = new Date(`${selectedDate}T${selectedTime}:00+08:00`).getTime();

  if (!selectedDate || !selectedTime || Number.isNaN(nextTarget)) return;

  targetTimestamp = nextTarget;
  isCustomTarget = true;
  renderTargetDetails();
  renderCountdown();
  closeCustomDialog();
});

renderTargetDetails();
renderCountdown();
setInterval(renderCountdown, 250);
