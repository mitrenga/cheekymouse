SELECT `ndx`, `name`, `score`, `created`
FROM `rg_cm_hallOfFame`
ORDER BY `ndx` DESC
LIMIT :limit
