ALTER TABLE user
ADD COLUMN firstname VARCHAR(200) NOT NULL,
ADD COLUMN lastname VARCHAR(200) NOT NULL;

select * from user;